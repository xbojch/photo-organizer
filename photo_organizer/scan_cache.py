"""What analyze() already worked out about each input file, so the next
scan doesn't redo it.

hashes.json (hashdb.py) answers "has a file with this *content* already
been organized?" -- but to ask that, analyze() first needs the input
file's hash, which means reading the whole file. On a large library that
reading is most of the scan time, repeated in full on every run.

This cache remembers, per input file path, the file's size and modified
time together with its hash, date and GPS. On the next scan, a file whose
size and modified time are unchanged reuses all of that without being
opened; only new or changed files are read. It lives next to hashes.json,
at ``<out_dir>/scan_cache.json``, and is written during Analyze -- dry runs
included, so the expensive part of a dry run isn't thrown away.

Size + modified time is the usual "unchanged" check (the same one rsync
and make use): a file edited in place without either changing would keep
its old cached values.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import DateSource

FILENAME = 'scan_cache.json'
_VERSION = 1


@dataclass
class CachedScan:
    hash: str
    date: datetime
    source: DateSource
    gps: tuple[float, float] | None
    gps_read: bool  # GPS was looked up (only done with "Group by location" on)
    exiftool: bool  # exiftool was configured when date/GPS were read


class ScanCache:
    def __init__(self, out_dir: Path):
        self.path = out_dir / FILENAME
        self._entries: dict[str, dict] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def load(self) -> None:
        """Best effort: an unreadable or foreign file just means an empty cache."""
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        if isinstance(raw, dict) and raw.get('version') == _VERSION and isinstance(raw.get('files'), dict):
            self._entries = raw['files']

    def save(self) -> None:
        """Write atomically, so a crash mid-write never leaves a broken file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + '.tmp')
        tmp.write_text(json.dumps({'version': _VERSION, 'files': self._entries}, ensure_ascii=False),
                       encoding='utf-8')
        os.replace(tmp, self.path)

    @staticmethod
    def _key(path: Path) -> str:
        return str(path.absolute())

    def get(self, path: Path, st: os.stat_result) -> CachedScan | None:
        """The cached scan for path, or None if missing or the file changed."""
        e = self._entries.get(self._key(path))
        if not e or e.get('size') != st.st_size or e.get('mtime_ns') != st.st_mtime_ns:
            return None
        try:
            gps = e.get('gps')
            return CachedScan(
                hash=e['hash'],
                date=datetime.fromisoformat(e['date']),
                source=DateSource(e['source']),
                gps=(float(gps[0]), float(gps[1])) if gps else None,
                gps_read=bool(e.get('gps_read')),
                exiftool=bool(e.get('exiftool')),
            )
        except (KeyError, TypeError, ValueError, IndexError):
            return None  # malformed entry -- rescan the file

    def put(self, path: Path, st: os.stat_result, scan: CachedScan) -> None:
        self._entries[self._key(path)] = {
            'size': st.st_size,
            'mtime_ns': st.st_mtime_ns,
            'hash': scan.hash,
            'date': scan.date.isoformat(),
            'source': scan.source.value,
            'gps': list(scan.gps) if scan.gps else None,
            'gps_read': scan.gps_read,
            'exiftool': scan.exiftool,
        }

    def prune(self, in_dir: Path, seen: set[str]) -> int:
        """Drop entries under in_dir that this (complete) scan didn't see --
        files that were moved or deleted since. Entries from other input
        folders are kept. Returns how many were dropped."""
        prefix = self._key(in_dir).rstrip(os.sep) + os.sep
        stale = [k for k in self._entries if k.startswith(prefix) and k not in seen]
        for k in stale:
            del self._entries[k]
        return len(stale)
