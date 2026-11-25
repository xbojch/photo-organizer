"""One way to run exiftool, shared by dates.py, gps.py and exif_lookup.py.

Starting a new exiftool process per file is the slow part of a scan: it's a
Perl program, so every launch pays for interpreter start-up before it reads
a single tag. Inside an ``exiftool_session()`` block, run_exiftool() instead
sends each request to one long-running process (exiftool's ``-stay_open``
mode), which answers in milliseconds. Outside a session it falls back to a
plain one-off subprocess.run(), exactly as before.

The process is started lazily, on the first request, so a session that is
never used (no exiftool configured, or every file answered from the scan
cache) never spawns anything.

Protocol: arguments are written to exiftool's stdin one per line, followed
by ``-executeN``; exiftool runs them and prints ``{readyN}`` after the
output. The numbered marker lets us tell this request's output apart from
anything left over from an earlier one.
"""
from __future__ import annotations

import os
import queue
import subprocess  # nosec B404 -- only ever invoked with a fixed, user-configured exiftool path
import threading
from contextlib import contextmanager
from typing import Iterator

# exiftool is a console executable; without this, each launch briefly opens
# and focuses its own console window on Windows.
CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0

TIMEOUT_SECONDS = 20


class _Session:
    """A lazily started ``exiftool -stay_open True -@ -`` process."""

    def __init__(self, exiftool_path: str):
        self.exiftool_path = exiftool_path
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._counter = 0
        self.broken = False  # couldn't start at all -- stop retrying

    def _start(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        if self.broken:
            return False
        try:
            self._proc = subprocess.Popen(  # nosec B603 -- exiftool_path is app-configured, args are fixed
                [self.exiftool_path, '-stay_open', 'True', '-@', '-'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf-8', errors='replace', creationflags=CREATE_NO_WINDOW,
            )
        except OSError:
            self.broken = True
            self._proc = None
            return False
        # A reader thread feeds stdout into a queue, so a hung exiftool (a
        # pathological file) can be timed out instead of blocking forever.
        self._lines = queue.Queue()
        threading.Thread(target=self._pump, args=(self._proc, self._lines), daemon=True).start()
        return True

    @staticmethod
    def _pump(proc: subprocess.Popen, lines: queue.Queue) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)  # EOF: the process exited

    def _kill(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
                self._proc.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass
            self._proc = None

    def run(self, args: list[str]) -> str | None:
        """Run one request; return its stdout, or None on failure/timeout."""
        if not self._start():
            return None
        assert self._proc is not None and self._proc.stdin is not None
        self._counter += 1
        marker = f'{{ready{self._counter}}}'
        # -charset filename=utf8 so non-ASCII paths survive on Windows.
        request = ['-charset', 'filename=utf8', *args, f'-execute{self._counter}']
        try:
            self._proc.stdin.write(''.join(f'{a}\n' for a in request))
            self._proc.stdin.flush()
        except (OSError, ValueError):
            self._kill()
            return None

        out: list[str] = []
        while True:
            try:
                line = self._lines.get(timeout=TIMEOUT_SECONDS)
            except queue.Empty:
                self._kill()  # hung on this file -- restart for the next one
                return None
            if line is None:
                self._kill()  # crashed -- restart for the next one
                return None
            if line.strip() == marker:
                return ''.join(out)
            out.append(line)

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            assert self._proc.stdin is not None
            self._proc.stdin.write('-stay_open\nFalse\n')
            self._proc.stdin.flush()
            self._proc.wait(timeout=5)
        except (OSError, ValueError, subprocess.SubprocessError):
            self._kill()
        self._proc = None


_session: _Session | None = None


@contextmanager
def exiftool_session(exiftool_path: str) -> Iterator[None]:
    """Route every run_exiftool() call inside this block through one
    long-running exiftool process. A no-op when exiftool_path is empty."""
    global _session
    if not exiftool_path:
        yield
        return
    previous, _session = _session, _Session(exiftool_path)
    try:
        yield
    finally:
        _session.close()
        _session = previous


def run_exiftool(exiftool_path: str, args: list[str]) -> str | None:
    """stdout of ``exiftool <args>``, or None if it couldn't be run."""
    if _session is not None and _session.exiftool_path == exiftool_path:
        out = _session.run(args)
        # None here means this file hung or crashed exiftool (the session
        # restarts for the next file) -- don't retry it as a one-off call,
        # that would just wait out the same timeout again. Only when the
        # session couldn't start at all, fall through to the one-off path.
        if out is not None or not _session.broken:
            return out
    try:
        proc = subprocess.run(  # nosec B603 -- exiftool_path is app-configured, args are fixed/path-only
            [exiftool_path, *args],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS, creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout or ''
