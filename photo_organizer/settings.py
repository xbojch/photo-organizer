"""Persisted GUI settings, saved as JSON next to the app (see paths.app_dir())
-- this is a portable single-exe tool with no installer, so settings live
alongside it rather than in the registry or %APPDATA%.

dry_run is deliberately never persisted: always starting a fresh launch in
dry-run mode is a safety net against a stale "apply for real" setting from a
previous session silently carrying over onto a different input/output pair.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields

from .paths import app_dir

SETTINGS_FILENAME = 'settings.json'


@dataclass
class Settings:
    input_dir: str = ''
    output_dir: str = ''
    operation: str = 'Copy'
    group_by_location: bool = False
    excluded_locations: str = ''
    exiftool_path: str = ''

    @classmethod
    def load(cls) -> Settings:
        path = app_dir() / SETTINGS_FILENAME
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        path = app_dir() / SETTINGS_FILENAME
        try:
            path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding='utf-8')
        except OSError:
            pass


def parse_excluded_locations(raw: str) -> frozenset[str]:
    """Comma-separated free text -> a set of trimmed, non-empty entries."""
    return frozenset(s.strip() for s in raw.split(',') if s.strip())
