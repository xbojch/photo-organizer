"""Tests for the long-running exiftool session (exiftool.py)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from photo_organizer import exiftool
from photo_organizer.exiftool import exiftool_session, run_exiftool

REAL_EXIFTOOL = shutil.which('exiftool')
needs_exiftool = pytest.mark.skipif(not REAL_EXIFTOOL, reason='exiftool not installed')
posix_only = pytest.mark.skipif(os.name == 'nt', reason='uses a shebang script as a fake exiftool')


class _FakeCompleted:
    def __init__(self, stdout: str):
        self.stdout = stdout


def _count_popen(monkeypatch) -> list[list[str]]:
    started: list[list[str]] = []
    real_popen = subprocess.Popen

    def counting(args, *a, **kw):
        started.append(list(args))
        return real_popen(args, *a, **kw)

    monkeypatch.setattr(subprocess, 'Popen', counting)
    return started


def _write_fake_exiftool(path: Path, body: str) -> str:
    path.write_text(f'#!{sys.executable}\n{body}', encoding='utf-8')
    path.chmod(0o755)
    return str(path)


def test_without_a_session_each_call_is_a_one_off_subprocess(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, 'run', lambda args, **kw: calls.append(args) or _FakeCompleted('x\n'))

    assert run_exiftool('exiftool', ['-ver']) == 'x\n'
    assert calls == [['exiftool', '-ver']]


def test_an_empty_exiftool_path_session_is_a_no_op(monkeypatch):
    started = _count_popen(monkeypatch)
    with exiftool_session(''):
        assert exiftool._session is None
    assert started == []


def test_a_session_that_is_never_used_starts_no_process(monkeypatch):
    started = _count_popen(monkeypatch)
    with exiftool_session('/usr/bin/exiftool'):
        pass
    assert started == []


@needs_exiftool
def test_a_session_gives_the_same_output_as_one_off_calls_from_one_process(tmp_path, monkeypatch):
    files = []
    for name in ('a.txt', 'b c.txt', 'Łódź.txt'):  # spaces and non-ASCII names too
        (tmp_path / name).write_text('hello', encoding='utf-8')
        files.append(tmp_path / name)
    expected = [run_exiftool(REAL_EXIFTOOL, ['-s3', '-FileName', str(f)]) for f in files]
    assert expected == ['a.txt\n', 'b c.txt\n', 'Łódź.txt\n']

    started = _count_popen(monkeypatch)
    with exiftool_session(REAL_EXIFTOOL):
        got = [run_exiftool(REAL_EXIFTOOL, ['-s3', '-FileName', str(f)]) for f in files]

    assert got == expected
    assert len(started) == 1


@needs_exiftool
def test_a_session_survives_a_missing_file(tmp_path):
    (tmp_path / 'a.txt').write_text('hello', encoding='utf-8')
    with exiftool_session(REAL_EXIFTOOL):
        assert run_exiftool(REAL_EXIFTOOL, ['-s3', '-FileName', str(tmp_path / 'nope.txt')]) == ''
        assert run_exiftool(REAL_EXIFTOOL, ['-s3', '-FileName', str(tmp_path / 'a.txt')]) == 'a.txt\n'


@posix_only
def test_a_hung_exiftool_times_out_and_is_restarted_without_a_one_off_retry(tmp_path, monkeypatch):
    fake = _write_fake_exiftool(tmp_path / 'exiftool', 'import sys, time\nsys.stdin.read()\ntime.sleep(60)\n')
    monkeypatch.setattr(exiftool, 'TIMEOUT_SECONDS', 0.5)
    one_offs = []
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: one_offs.append(a))
    started = _count_popen(monkeypatch)

    with exiftool_session(fake):
        assert run_exiftool(fake, ['-s3', 'x.jpg']) is None
        assert run_exiftool(fake, ['-s3', 'y.jpg']) is None

    assert one_offs == []  # a hang isn't retried as a one-off call (it would just hang again)
    assert len(started) == 2  # killed after the first hang, restarted for the next file


def test_a_session_that_cannot_start_falls_back_to_one_off_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, 'run', lambda args, **kw: calls.append(args) or _FakeCompleted('x\n'))

    with exiftool_session('/nonexistent/exiftool'):
        assert run_exiftool('/nonexistent/exiftool', ['-ver']) == 'x\n'
        assert run_exiftool('/nonexistent/exiftool', ['-ver']) == 'x\n'

    assert len(calls) == 2


def test_the_session_ends_with_the_block(tmp_path):
    with exiftool_session('/usr/bin/exiftool'):
        assert exiftool._session is not None
    assert exiftool._session is None
