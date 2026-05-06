"""State module load/save for state.json, books.json, and highlight snapshots."""

import json
from datetime import date
from pathlib import Path

from readwise_review.state import (
    BookEntry,
    BooksFile,
    Highlight,
    HighlightSnapshot,
    HistoryEntry,
    State,
    load_books,
    load_snapshot,
    load_state,
    save_books,
    save_snapshot,
    save_state,
)


def test_state_round_trip(tmp_path: Path) -> None:
    state = State(
        current_book_id=12345,
        current_book_started_on=date(2026, 5, 1),
        position=24,
        last_send_date=date(2026, 5, 4),
        picker_email_sent_on=None,
        bootstrap_consumed=True,
        history=[
            HistoryEntry(
                book_id=9876,
                started=date(2026, 4, 1),
                finished=date(2026, 4, 30),
                abandoned_at=None,
                position_at_abandon=None,
                highlight_count=47,
                outcome="completed",
            ),
        ],
    )
    path = tmp_path / "state.json"
    save_state(state, path)

    loaded = load_state(path)

    assert loaded == state


def test_state_handles_null_dates(tmp_path: Path) -> None:
    state = State(
        current_book_id=None,
        current_book_started_on=None,
        position=0,
        last_send_date=None,
        picker_email_sent_on=None,
        bootstrap_consumed=False,
        history=[],
    )
    path = tmp_path / "state.json"
    save_state(state, path)

    loaded = load_state(path)

    assert loaded == state


def test_state_history_handles_abandoned_entries(tmp_path: Path) -> None:
    state = State(
        current_book_id=None,
        current_book_started_on=None,
        position=0,
        last_send_date=date(2026, 5, 4),
        picker_email_sent_on=date(2026, 5, 4),
        bootstrap_consumed=True,
        history=[
            HistoryEntry(
                book_id=5555,
                started=date(2026, 3, 15),
                finished=None,
                abandoned_at=date(2026, 4, 1),
                position_at_abandon=12,
                highlight_count=60,
                outcome="abandoned",
            ),
        ],
    )
    path = tmp_path / "state.json"
    save_state(state, path)
    loaded = load_state(path)
    assert loaded == state


def test_books_round_trip(tmp_path: Path) -> None:
    books = BooksFile(
        fetched_at="2026-05-03T12:00:00Z",
        books=[
            BookEntry(id=12345, title="The Beginning of Infinity", author="David Deutsch", num_highlights=87),
            BookEntry(id=9876, title="Antifragile", author="Nassim Taleb", num_highlights=54),
        ],
    )
    path = tmp_path / "books.json"
    save_books(books, path)

    assert load_books(path) == books


def test_books_handles_null_author(tmp_path: Path) -> None:
    books = BooksFile(
        fetched_at="2026-05-03T12:00:00Z",
        books=[BookEntry(id=1, title="Anonymous Book", author=None, num_highlights=3)],
    )
    path = tmp_path / "books.json"
    save_books(books, path)
    assert load_books(path) == books


def test_snapshot_round_trip(tmp_path: Path) -> None:
    snapshot = HighlightSnapshot(
        book_id=12345,
        snapshotted_at="2026-05-01T12:01:23Z",
        highlights=[
            Highlight(
                id=555,
                text="The fundamental belief...",
                location=42,
                location_type="page",
                note="Important",
                highlighted_at="2024-08-12T14:23:00Z",
            ),
            Highlight(
                id=556,
                text="Another quote.",
                location=None,
                location_type="page",
                note="",
                highlighted_at=None,
            ),
        ],
    )
    path = tmp_path / "snapshot.json"
    save_snapshot(snapshot, path)

    assert load_snapshot(path) == snapshot


def test_state_file_is_pretty_printed(tmp_path: Path) -> None:
    """Diffs in commits should be readable; state files are pretty-printed."""
    state = State(
        current_book_id=1,
        current_book_started_on=date(2026, 5, 1),
        position=0,
        last_send_date=None,
        picker_email_sent_on=None,
        bootstrap_consumed=False,
        history=[],
    )
    path = tmp_path / "state.json"
    save_state(state, path)
    raw = path.read_text()
    assert "\n  " in raw
