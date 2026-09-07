"""Tests for persisted GUI settings (photo_organizer/settings.py)."""
from __future__ import annotations

from photo_organizer.settings import Settings, parse_excluded_locations


def test_load_returns_defaults_when_no_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr('photo_organizer.settings.app_dir', lambda: tmp_path)
    settings = Settings.load()
    assert settings == Settings()


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr('photo_organizer.settings.app_dir', lambda: tmp_path)
    original = Settings(
        input_dir=str(tmp_path / 'in'),
        output_dir=str(tmp_path / 'out'),
        operation='Move',
        group_by_location=True,
        excluded_locations='Chmielowice, Home Town',
        exiftool_path=str(tmp_path / 'exiftool.exe'),
    )
    original.save()

    loaded = Settings.load()

    assert loaded == original


def test_load_ignores_a_corrupt_settings_file(tmp_path, monkeypatch):
    monkeypatch.setattr('photo_organizer.settings.app_dir', lambda: tmp_path)
    (tmp_path / 'settings.json').write_text('not json', encoding='utf-8')

    assert Settings.load() == Settings()


def test_load_ignores_unknown_fields_from_a_future_version(tmp_path, monkeypatch):
    monkeypatch.setattr('photo_organizer.settings.app_dir', lambda: tmp_path)
    (tmp_path / 'settings.json').write_text(
        '{"operation": "Move", "some_future_field": 123}', encoding='utf-8')

    loaded = Settings.load()

    assert loaded.operation == 'Move'


def test_parse_excluded_locations_trims_and_drops_empties():
    assert parse_excluded_locations(' Chmielowice ,, Home Town ,') == {'Chmielowice', 'Home Town'}


def test_parse_excluded_locations_empty_string_is_empty_set():
    assert parse_excluded_locations('') == frozenset()
