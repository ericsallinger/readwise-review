"""Shared pytest fixtures for unit tests."""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


CHICAGO = ZoneInfo("America/Chicago")


@pytest.fixture
def chicago_7am() -> datetime:
    """A weekday morning at exactly 7:00 Chicago time, used as the canonical 'now' in tests."""
    return datetime(2026, 5, 6, 7, 0, 0, tzinfo=CHICAGO)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """A clean data directory with the standard layout (state.json, books.json, highlights/)."""
    d = tmp_path / "data"
    d.mkdir()
    (d / "state.json").write_text(json.dumps({
        "current_book_id": None,
        "current_book_started_on": None,
        "position": 0,
        "last_send_date": None,
        "picker_email_sent_on": None,
        "bootstrap_consumed": False,
        "history": [],
    }))
    (d / "books.json").write_text(json.dumps({
        "fetched_at": None,
        "books": [],
    }))
    (d / "highlights").mkdir()
    return d
