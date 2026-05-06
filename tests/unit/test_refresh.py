"""Refresh entrypoint: writes books.json from Readwise list_books()."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from readwise_review.refresh import run as run_refresh
from readwise_review.state import BookEntry


def test_refresh_writes_only_books_with_highlights_sorted_by_title(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "books.json").write_text(json.dumps({"fetched_at": None, "books": []}))

    client = MagicMock()
    client.list_books.return_value = iter([
        BookEntry(id=1, title="Zebra", author=None, num_highlights=5),
        BookEntry(id=2, title="Apple", author="A", num_highlights=0),
        BookEntry(id=3, title="middle", author="B", num_highlights=2),
    ])

    committed: list[tuple[str, list[str]]] = []
    def fake_commit(msg, files, cwd=None):
        committed.append((msg, files))
        return True

    run_refresh(
        client=client,
        data_dir=data,
        commit_fn=fake_commit,
    )

    raw = json.loads((data / "books.json").read_text())
    assert [b["id"] for b in raw["books"]] == [3, 1]
    assert raw["fetched_at"] is not None
    assert committed and committed[0][1] == ["data/books.json"]


def test_refresh_invokes_commit_fn_even_when_only_fetched_at_changed(tmp_path: Path) -> None:
    """commit_fn is responsible for diffing; refresh always asks it to commit."""
    data = tmp_path / "data"
    data.mkdir()
    initial = {
        "fetched_at": "2026-04-01T00:00:00Z",
        "books": [{"id": 1, "title": "Same", "author": "A", "num_highlights": 3}],
    }
    (data / "books.json").write_text(json.dumps(initial, indent=2) + "\n")

    client = MagicMock()
    client.list_books.return_value = iter([
        BookEntry(id=1, title="Same", author="A", num_highlights=3),
    ])

    commit_called: list[str] = []
    def fake_commit(msg, files, cwd=None):
        commit_called.append(msg)
        return True

    run_refresh(
        client=client,
        data_dir=data,
        commit_fn=fake_commit,
    )

    assert commit_called
