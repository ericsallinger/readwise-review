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


def _seed_book_with_highlights(
    data_dir: Path, book_id: int, count: int, position: int = 0
) -> None:
    today = date(2026, 5, 1)
    state = State(
        current_book_id=book_id,
        current_book_started_on=today,
        position=position,
        last_send_date=None,
        picker_email_sent_on=None,
        bootstrap_consumed=True,
        history=[],
    )
    save_state(state, data_dir / "state.json")
    snap = HighlightSnapshot(
        book_id=book_id,
        snapshotted_at="2026-05-01T12:00:00Z",
        highlights=[
            Highlight(id=i, text=f"Quote {i}", location=i, location_type="page", note="", highlighted_at=None)
            for i in range(count)
        ],
    )
    save_snapshot(snap, data_dir / "highlights" / f"{book_id}.json")
    save_books(BooksFile(
        fetched_at="2026-05-01T12:00:00Z",
        books=[BookEntry(id=book_id, title="My Book", author="Author", num_highlights=count)],
    ), data_dir / "books.json")


def test_regular_highlights_email(
    config, tmp_path, email_sent, send_email_fake, commit_fn_fake
):
    today = date(2026, 5, 6)
    d = tmp_path / "data"
    d.mkdir()
    (d / "highlights").mkdir()
    _seed_book_with_highlights(d, book_id=42, count=20, position=4)

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

    assert len(email_sent) == 1
    assert email_sent[0]["subject"] == "Readwise: My Book — 5–12 of 20"
    assert "Pick the next book" not in email_sent[0]["html"]

    s = load_state(d / "state.json")
    assert s.position == 12
    assert s.last_send_date == today


def test_finishing_email_when_remaining_fits_in_one_email(
    config, tmp_path, email_sent, send_email_fake, commit_fn_fake
):
    today = date(2026, 5, 6)
    d = tmp_path / "data"
    d.mkdir()
    (d / "highlights").mkdir()
    _seed_book_with_highlights(d, book_id=42, count=10, position=6)
    save_books(BooksFile(
        fetched_at="2026-05-01T12:00:00Z",
        books=[
            BookEntry(id=42, title="My Book", author="Author", num_highlights=10),
            BookEntry(id=99, title="Other Book", author="Other Author", num_highlights=20),
        ],
    ), d / "books.json")

    client = MagicMock()
    client.list_books.return_value = iter([
        BookEntry(id=42, title="My Book", author="Author", num_highlights=10),
        BookEntry(id=99, title="Other Book", author="Other Author", num_highlights=20),
    ])

    run_daily(
        config=config,
        data_dir=d,
        client=client,
        send_email_fn=send_email_fake,
        commit_fn=commit_fn_fake,
        gmail_app_password="pw",
        repo="user/repo",
        now=_seven_am(today),
    )

    assert len(email_sent) == 1
    assert email_sent[0]["subject"] == "Readwise: My Book — 7–10 of 10"
    assert "Choose your next book" in email_sent[0]["html"]
    assert "Finished" in email_sent[0]["html"]

    s = load_state(d / "state.json")
    assert s.current_book_id is None
    assert s.current_book_started_on is None
    assert s.position == 0
    assert s.picker_email_sent_on == today
    assert s.last_send_date == today
    assert len(s.history) == 1
    assert s.history[0].book_id == 42
    assert s.history[0].finished == today
    assert s.history[0].outcome == "completed"
    assert s.history[0].highlight_count == 10


def test_smtp_failure_leaves_state_unchanged(
    config, tmp_path, commit_fn_fake
):
    today = date(2026, 5, 6)
    d = tmp_path / "data"
    d.mkdir()
    (d / "highlights").mkdir()
    _seed_book_with_highlights(d, book_id=42, count=20, position=4)
    state_before = load_state(d / "state.json")

    def failing_send(*args, **kwargs):
        raise RuntimeError("SMTP down")

    with pytest.raises(RuntimeError):
        run_daily(
            config=config,
            data_dir=d,
            client=MagicMock(),
            send_email_fn=failing_send,
            commit_fn=commit_fn_fake,
            gmail_app_password="pw",
            repo="user/repo",
            now=_seven_am(today),
        )

    state_after = load_state(d / "state.json")
    assert state_after == state_before


def test_bootstrap_path_snapshots_book_and_sends_first_highlights(
    tmp_path, email_sent, send_email_fake, commit_fn_fake
):
    today = date(2026, 5, 6)
    config = Config(
        highlights_per_email=8,
        to_email="to@example.com",
        from_email="from@example.com",
        timezone="America/Chicago",
        bootstrap_book_id=42,
    )
    d = tmp_path / "data"
    d.mkdir()
    (d / "highlights").mkdir()
    save_state(State(
        current_book_id=None,
        current_book_started_on=None,
        position=0,
        last_send_date=None,
        picker_email_sent_on=None,
        bootstrap_consumed=False,
        history=[],
    ), d / "state.json")
    save_books(BooksFile(
        fetched_at="2026-05-01T12:00:00Z",
        books=[BookEntry(id=42, title="Bootstrap Book", author="Author", num_highlights=20)],
    ), d / "books.json")

    client = MagicMock()
    client.get_highlights.return_value = iter([
        Highlight(id=i, text=f"Quote {i}", location=i, location_type="page", note="", highlighted_at=None)
        for i in range(20)
    ])

    run_daily(
        config=config,
        data_dir=d,
        client=client,
        send_email_fn=send_email_fake,
        commit_fn=commit_fn_fake,
        gmail_app_password="pw",
        repo="user/repo",
        now=_seven_am(today),
    )

    snap_path = d / "highlights" / "42.json"
    assert snap_path.exists()
    assert len(email_sent) == 1
    assert email_sent[0]["subject"] == "Readwise: Bootstrap Book — 1–8 of 20"
    s = load_state(d / "state.json")
    assert s.current_book_id == 42
    assert s.current_book_started_on == today
    assert s.bootstrap_consumed is True
    assert s.position == 8
    assert s.last_send_date == today
