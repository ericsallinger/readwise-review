"""Persistent state: state.json, books.json, highlight snapshots.

Dates round-trip as ISO-8601 strings; instants (`*_at` fields) round-trip
as ISO-8601 strings too but we store them as plain strings without parsing —
they are produced by Readwise or by Python's `datetime.now(tz=UTC).isoformat()`
and we only ever pass them through.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal


# ---- state.json ---------------------------------------------------------

Outcome = Literal["completed", "abandoned"]


@dataclass(frozen=True)
class HistoryEntry:
    book_id: int
    started: date | None
    finished: date | None
    abandoned_at: date | None
    position_at_abandon: int | None
    highlight_count: int
    outcome: Outcome


@dataclass(frozen=True)
class State:
    current_book_id: int | None
    current_book_started_on: date | None
    position: int
    last_send_date: date | None
    picker_email_sent_on: date | None
    bootstrap_consumed: bool
    history: list[HistoryEntry] = field(default_factory=list)


def _date_to_str(d: date | None) -> str | None:
    return d.isoformat() if d is not None else None


def _date_from_str(s: str | None) -> date | None:
    return date.fromisoformat(s) if s is not None else None


def state_to_dict(state: State) -> dict:
    return {
        "current_book_id": state.current_book_id,
        "current_book_started_on": _date_to_str(state.current_book_started_on),
        "position": state.position,
        "last_send_date": _date_to_str(state.last_send_date),
        "picker_email_sent_on": _date_to_str(state.picker_email_sent_on),
        "bootstrap_consumed": state.bootstrap_consumed,
        "history": [
            {
                "book_id": h.book_id,
                "started": _date_to_str(h.started),
                "finished": _date_to_str(h.finished),
                "abandoned_at": _date_to_str(h.abandoned_at),
                "position_at_abandon": h.position_at_abandon,
                "highlight_count": h.highlight_count,
                "outcome": h.outcome,
            }
            for h in state.history
        ],
    }


def state_from_dict(d: dict) -> State:
    return State(
        current_book_id=d["current_book_id"],
        current_book_started_on=_date_from_str(d["current_book_started_on"]),
        position=d["position"],
        last_send_date=_date_from_str(d["last_send_date"]),
        picker_email_sent_on=_date_from_str(d["picker_email_sent_on"]),
        bootstrap_consumed=d["bootstrap_consumed"],
        history=[
            HistoryEntry(
                book_id=h["book_id"],
                started=_date_from_str(h["started"]),
                finished=_date_from_str(h["finished"]),
                abandoned_at=_date_from_str(h["abandoned_at"]),
                position_at_abandon=h["position_at_abandon"],
                highlight_count=h["highlight_count"],
                outcome=h["outcome"],
            )
            for h in d["history"]
        ],
    )


def load_state(path: Path | str) -> State:
    return state_from_dict(json.loads(Path(path).read_text()))


def save_state(state: State, path: Path | str) -> None:
    Path(path).write_text(json.dumps(state_to_dict(state), indent=2) + "\n")


# ---- books.json ---------------------------------------------------------

@dataclass(frozen=True)
class BookEntry:
    id: int
    title: str
    author: str | None
    num_highlights: int


@dataclass(frozen=True)
class BooksFile:
    fetched_at: str | None
    books: list[BookEntry]


def load_books(path: Path | str) -> BooksFile:
    raw = json.loads(Path(path).read_text())
    return BooksFile(
        fetched_at=raw["fetched_at"],
        books=[BookEntry(**b) for b in raw["books"]],
    )


def save_books(books: BooksFile, path: Path | str) -> None:
    payload = {
        "fetched_at": books.fetched_at,
        "books": [asdict(b) for b in books.books],
    }
    Path(path).write_text(json.dumps(payload, indent=2) + "\n")


# ---- highlights/<book_id>.json ------------------------------------------

@dataclass(frozen=True)
class Highlight:
    id: int
    text: str
    location: int | None
    location_type: str
    note: str
    highlighted_at: str | None


@dataclass(frozen=True)
class HighlightSnapshot:
    book_id: int
    snapshotted_at: str
    highlights: list[Highlight]


def load_snapshot(path: Path | str) -> HighlightSnapshot:
    raw = json.loads(Path(path).read_text())
    return HighlightSnapshot(
        book_id=raw["book_id"],
        snapshotted_at=raw["snapshotted_at"],
        highlights=[Highlight(**h) for h in raw["highlights"]],
    )


def save_snapshot(snapshot: HighlightSnapshot, path: Path | str) -> None:
    payload = {
        "book_id": snapshot.book_id,
        "snapshotted_at": snapshot.snapshotted_at,
        "highlights": [asdict(h) for h in snapshot.highlights],
    }
    Path(path).write_text(json.dumps(payload, indent=2) + "\n")


def snapshot_path(data_dir: Path | str, book_id: int) -> Path:
    return Path(data_dir) / "highlights" / f"{book_id}.json"
