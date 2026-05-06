"""Select entrypoint: parses issue, snapshots book, updates state, comments + closes issue."""

import json
from dataclasses import replace as dc_replace
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from readwise_review.select import (
    InvalidIssueError,
    parse_book_id,
    run as run_select,
)
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


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
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
        books=[
            BookEntry(id=42, title="My Book", author="Author", num_highlights=10),
            BookEntry(id=99, title="Other", author="Other Author", num_highlights=20),
        ],
    ), d / "books.json")
    (d / "highlights").mkdir()
    return d


# ---- title parsing -------------------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("select-book: 42", 42),
    ("select-book:42", 42),
    ("select-book:  12345", 12345),
])
def test_parse_book_id_valid(title: str, expected: int) -> None:
    assert parse_book_id(title) == expected


@pytest.mark.parametrize("title", [
    "select-book:",
    "select-book: abc",
    "selectbook: 42",
    "random title",
])
def test_parse_book_id_invalid_raises(title: str) -> None:
    with pytest.raises(InvalidIssueError):
        parse_book_id(title)


# ---- happy path ----------------------------------------------------------

def test_select_book_happy_path(data_dir: Path) -> None:
    today = date(2026, 5, 6)
    client = MagicMock()
    client.get_highlights.return_value = iter([
        Highlight(id=1, text="A", location=2, location_type="page", note="", highlighted_at=None),
        Highlight(id=2, text="B", location=1, location_type="page", note="", highlighted_at=None),
    ])
    client.list_books.return_value = iter([
        BookEntry(id=42, title="My Book", author="Author", num_highlights=2),
        BookEntry(id=99, title="Other", author="Other Author", num_highlights=20),
    ])
    comments: list[str] = []
    closed: list[bool] = []

    run_select(
        issue_title="select-book: 42",
        issue_user="ericsallinger",
        issue_number=7,
        repo_owner="ericsallinger",
        client=client,
        data_dir=data_dir,
        commit_fn=lambda *a, **k: True,
        comment_fn=lambda body: comments.append(body),
        close_fn=lambda: closed.append(True),
        now_chicago_date=today,
    )

    s = load_state(data_dir / "state.json")
    assert s.current_book_id == 42
    assert s.current_book_started_on == today
    assert s.position == 0
    assert s.picker_email_sent_on is None
    snap_path = data_dir / "highlights" / "42.json"
    raw = json.loads(snap_path.read_text())
    assert [h["id"] for h in raw["highlights"]] == [2, 1]
    assert closed == [True]
    assert comments and "Selected" in comments[0]


# ---- skip non-owner / wrong-prefix issues -------------------------------

def test_select_skips_when_not_owner(data_dir: Path) -> None:
    client = MagicMock()
    closed: list[bool] = []
    run_select(
        issue_title="select-book: 42",
        issue_user="some-other-user",
        issue_number=7,
        repo_owner="ericsallinger",
        client=client,
        data_dir=data_dir,
        commit_fn=lambda *a, **k: True,
        comment_fn=lambda b: None,
        close_fn=lambda: closed.append(True),
        now_chicago_date=date(2026, 5, 6),
    )
    assert closed == []
    client.get_highlights.assert_not_called()


def test_select_skips_when_title_lacks_prefix(data_dir: Path) -> None:
    client = MagicMock()
    closed: list[bool] = []
    run_select(
        issue_title="please review this PR",
        issue_user="ericsallinger",
        issue_number=7,
        repo_owner="ericsallinger",
        client=client,
        data_dir=data_dir,
        commit_fn=lambda *a, **k: True,
        comment_fn=lambda b: None,
        close_fn=lambda: closed.append(True),
        now_chicago_date=date(2026, 5, 6),
    )
    assert closed == []
    client.get_highlights.assert_not_called()


# ---- already-on-this-book idempotency -----------------------------------

def test_select_no_op_when_already_on_this_book(data_dir: Path) -> None:
    state = load_state(data_dir / "state.json")
    save_state(
        dc_replace(state, current_book_id=42, current_book_started_on=date(2026, 5, 1)),
        data_dir / "state.json",
    )
    client = MagicMock()
    comments: list[str] = []
    closed: list[bool] = []
    run_select(
        issue_title="select-book: 42",
        issue_user="ericsallinger",
        issue_number=7,
        repo_owner="ericsallinger",
        client=client,
        data_dir=data_dir,
        commit_fn=lambda *a, **k: True,
        comment_fn=lambda b: comments.append(b),
        close_fn=lambda: closed.append(True),
        now_chicago_date=date(2026, 5, 6),
    )
    client.get_highlights.assert_not_called()
    assert comments and "Already on this book" in comments[0]
    assert closed == [True]


# ---- abandonment of mid-cycle book --------------------------------------

def test_select_abandons_current_book_to_history(data_dir: Path) -> None:
    state = load_state(data_dir / "state.json")
    save_state(
        dc_replace(
            state,
            current_book_id=99,
            current_book_started_on=date(2026, 4, 1),
            position=5,
        ),
        data_dir / "state.json",
    )
    save_snapshot(HighlightSnapshot(
        book_id=99,
        snapshotted_at="2026-04-01T12:00:00Z",
        highlights=[Highlight(id=i, text=str(i), location=i, location_type="page", note="", highlighted_at=None) for i in range(20)],
    ), data_dir / "highlights" / "99.json")

    client = MagicMock()
    client.get_highlights.return_value = iter([
        Highlight(id=1, text="A", location=1, location_type="page", note="", highlighted_at=None),
    ])
    client.list_books.return_value = iter([
        BookEntry(id=42, title="My Book", author="Author", num_highlights=1),
        BookEntry(id=99, title="Other", author="Other Author", num_highlights=20),
    ])

    run_select(
        issue_title="select-book: 42",
        issue_user="ericsallinger",
        issue_number=7,
        repo_owner="ericsallinger",
        client=client,
        data_dir=data_dir,
        commit_fn=lambda *a, **k: True,
        comment_fn=lambda b: None,
        close_fn=lambda: None,
        now_chicago_date=date(2026, 5, 6),
    )

    s = load_state(data_dir / "state.json")
    assert s.current_book_id == 42
    assert s.current_book_started_on == date(2026, 5, 6)
    assert s.position == 0
    assert len(s.history) == 1
    assert s.history[0].book_id == 99
    assert s.history[0].outcome == "abandoned"
    assert s.history[0].abandoned_at == date(2026, 5, 6)
    assert s.history[0].position_at_abandon == 5
    assert s.history[0].highlight_count == 20


# ---- malformed title ----------------------------------------------------

def test_select_malformed_title_comments_and_closes(data_dir: Path) -> None:
    client = MagicMock()
    comments: list[str] = []
    closed: list[bool] = []
    run_select(
        issue_title="select-book: not-a-number",
        issue_user="ericsallinger",
        issue_number=7,
        repo_owner="ericsallinger",
        client=client,
        data_dir=data_dir,
        commit_fn=lambda *a, **k: True,
        comment_fn=lambda b: comments.append(b),
        close_fn=lambda: closed.append(True),
        now_chicago_date=date(2026, 5, 6),
    )
    client.get_highlights.assert_not_called()
    assert comments and "Could not parse" in comments[0]
    assert closed == [True]


# ---- unknown book id ---------------------------------------------------

def test_select_unknown_book_id_after_refresh_comments_and_closes(data_dir: Path) -> None:
    client = MagicMock()
    client.list_books.return_value = iter([
        BookEntry(id=42, title="My Book", author="Author", num_highlights=10),
        BookEntry(id=99, title="Other", author="Other Author", num_highlights=20),
    ])
    comments: list[str] = []
    closed: list[bool] = []
    run_select(
        issue_title="select-book: 999",
        issue_user="ericsallinger",
        issue_number=7,
        repo_owner="ericsallinger",
        client=client,
        data_dir=data_dir,
        commit_fn=lambda *a, **k: True,
        comment_fn=lambda b: comments.append(b),
        close_fn=lambda: closed.append(True),
        now_chicago_date=date(2026, 5, 6),
    )
    client.get_highlights.assert_not_called()
    assert comments and "not found" in comments[0]
    assert closed == [True]


# ---- empty highlights --------------------------------------------------

def test_select_book_with_zero_highlights_comments_and_closes(data_dir: Path) -> None:
    client = MagicMock()
    client.get_highlights.return_value = iter([])
    client.list_books.return_value = iter([
        BookEntry(id=42, title="My Book", author="Author", num_highlights=0),
    ])
    comments: list[str] = []
    closed: list[bool] = []
    run_select(
        issue_title="select-book: 42",
        issue_user="ericsallinger",
        issue_number=7,
        repo_owner="ericsallinger",
        client=client,
        data_dir=data_dir,
        commit_fn=lambda *a, **k: True,
        comment_fn=lambda b: comments.append(b),
        close_fn=lambda: closed.append(True),
        now_chicago_date=date(2026, 5, 6),
    )
    assert comments and "no highlights" in comments[0]
    assert closed == [True]
    s = load_state(data_dir / "state.json")
    assert s.current_book_id is None
