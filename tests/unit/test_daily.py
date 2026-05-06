"""Daily entrypoint: gating, branching, state persistence."""

from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from readwise_review.config import Config
from readwise_review.daily import run as run_daily
from readwise_review.state import (
    BookEntry,
    BooksFile,
    Highlight,
    HighlightSnapshot,
    State,
    load_state,
    save_books,
    save_snapshot,
    save_state,
)


CHICAGO = ZoneInfo("America/Chicago")


@pytest.fixture
def config() -> Config:
    return Config(
        highlights_per_email=8,
        to_email="to@example.com",
        from_email="from@example.com",
        timezone="America/Chicago",
        bootstrap_book_id=None,
    )


@pytest.fixture
def empty_state() -> State:
    return State(
        current_book_id=None,
        current_book_started_on=None,
        position=0,
        last_send_date=None,
        picker_email_sent_on=None,
        bootstrap_consumed=False,
        history=[],
    )


@pytest.fixture
def data_dir_with_state(tmp_path: Path, empty_state: State) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    save_state(empty_state, d / "state.json")
    save_books(BooksFile(fetched_at=None, books=[]), d / "books.json")
    (d / "highlights").mkdir()
    return d


@pytest.fixture
def email_sent() -> list:
    return []


@pytest.fixture
def send_email_fake(email_sent):
    def _fake(rendered, *, from_email, to_email, gmail_app_password):
        email_sent.append({
            "subject": rendered.subject,
            "html": rendered.html,
            "plain": rendered.plain,
            "from_email": from_email,
            "to_email": to_email,
        })
    return _fake


@pytest.fixture
def commit_fn_fake():
    def _fake(message: str, files: list[str], cwd: Path | None = None) -> bool:
        return True
    return _fake


def _seven_am(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 7, 0, 0, tzinfo=CHICAGO)


def _eight_am(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 8, 0, 0, tzinfo=CHICAGO)


def test_skip_if_not_seven_am(
    config, data_dir_with_state, email_sent, send_email_fake, commit_fn_fake
):
    run_daily(
        config=config,
        data_dir=data_dir_with_state,
        client=MagicMock(),
        send_email_fn=send_email_fake,
        commit_fn=commit_fn_fake,
        gmail_app_password="pw",
        repo="user/repo",
        now=_eight_am(date(2026, 5, 6)),
    )
    assert email_sent == []


def test_skip_if_already_sent_today(
    config, tmp_path, email_sent, send_email_fake, commit_fn_fake
):
    today = date(2026, 5, 6)
    state = State(
        current_book_id=None,
        current_book_started_on=None,
        position=0,
        last_send_date=today,
        picker_email_sent_on=today,
        bootstrap_consumed=False,
        history=[],
    )
    d = tmp_path / "data"
    d.mkdir()
    save_state(state, d / "state.json")
    save_books(BooksFile(fetched_at=None, books=[]), d / "books.json")
    (d / "highlights").mkdir()

    run_daily(
        config=config,
        data_dir=d,
        client=MagicMock(),
        send_email_fn=send_email_fake,
        commit_fn=commit_fn_fake,
        gmail_app_password="pw",
        repo="user/repo",
        now=_seven_am(today),
    )
    assert email_sent == []


def test_picker_email_when_no_book_and_no_picker_sent(
    config, data_dir_with_state, email_sent, send_email_fake, commit_fn_fake
):
    today = date(2026, 5, 6)
    client = MagicMock()
    client.list_books.return_value = iter([
        BookEntry(id=42, title="Antifragile", author="Nassim Taleb", num_highlights=10),
        BookEntry(id=99, title="Beginning of Infinity", author="David Deutsch", num_highlights=20),
    ])

    run_daily(
        config=config,
        data_dir=data_dir_with_state,
        client=client,
        send_email_fn=send_email_fake,
        commit_fn=commit_fn_fake,
        gmail_app_password="pw",
        repo="user/repo",
        now=_seven_am(today),
    )

    assert len(email_sent) == 1
    assert email_sent[0]["subject"] == "Readwise: pick a book to review"
    s = load_state(data_dir_with_state / "state.json")
    assert s.picker_email_sent_on == today
    assert s.last_send_date == today


def test_silence_when_no_book_and_picker_already_sent(
    config, tmp_path, email_sent, send_email_fake, commit_fn_fake
):
    today = date(2026, 5, 6)
    state = State(
        current_book_id=None,
        current_book_started_on=None,
        position=0,
        last_send_date=date(2026, 5, 4),
        picker_email_sent_on=date(2026, 5, 4),
        bootstrap_consumed=False,
        history=[],
    )
    d = tmp_path / "data"
    d.mkdir()
    save_state(state, d / "state.json")
    save_books(BooksFile(fetched_at=None, books=[]), d / "books.json")
    (d / "highlights").mkdir()

    run_daily(
        config=config,
        data_dir=d,
        client=MagicMock(),
        send_email_fn=send_email_fake,
        commit_fn=commit_fn_fake,
        gmail_app_password="pw",
        repo="user/repo",
        now=_seven_am(today),
    )

    assert email_sent == []
    s = load_state(d / "state.json")
    assert s.last_send_date == date(2026, 5, 4)
