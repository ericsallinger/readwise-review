"""Selection entrypoint triggered by `issues.opened` events.

Parses the issue title, snapshots the selected book's highlights, updates
state, comments + closes the issue. Designed for full unit testability:
all GitHub interactions and time are injected.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from readwise_review.config import load_config
from readwise_review.git_io import commit_and_push
from readwise_review.readwise import ReadwiseClient
from readwise_review.refresh import run as refresh_books_run
from readwise_review.state import (
    HighlightSnapshot,
    HistoryEntry,
    load_books,
    load_snapshot,
    load_state,
    save_snapshot,
    save_state,
    snapshot_path,
)


_TITLE_PREFIX = "select-book:"
_TITLE_RE = re.compile(r"^select-book:\s*(\d+)\s*$")


class InvalidIssueError(ValueError):
    pass


def parse_book_id(title: str) -> int:
    """Parses 'select-book: <id>' (with optional whitespace). Raises InvalidIssueError otherwise."""
    m = _TITLE_RE.match(title.strip())
    if not m:
        raise InvalidIssueError(
            f"Expected title format: 'select-book: <id>', got: {title!r}"
        )
    return int(m.group(1))


CommitFn = Callable[[str, list[str], Path | None], bool]
CommentFn = Callable[[str], None]
CloseFn = Callable[[], None]


def run(
    *,
    issue_title: str,
    issue_user: str,
    issue_number: int,
    repo_owner: str,
    client,
    data_dir: Path,
    commit_fn: CommitFn,
    comment_fn: CommentFn,
    close_fn: CloseFn,
    now_chicago_date: date,
) -> None:
    """Single entrypoint for select logic. All collaborators injected."""
    if issue_user != repo_owner:
        return
    if not issue_title.strip().startswith(_TITLE_PREFIX):
        return

    try:
        book_id = parse_book_id(issue_title)
    except InvalidIssueError as e:
        comment_fn(
            f"Could not parse book_id. Expected title format: select-book: <id>\n\n({e})"
        )
        close_fn()
        return

    state = load_state(data_dir / "state.json")

    if state.current_book_id == book_id:
        comment_fn("Already on this book.")
        close_fn()
        return

    books_file = load_books(data_dir / "books.json")
    if not any(b.id == book_id for b in books_file.books):
        refresh_books_run(client=client, data_dir=data_dir, commit_fn=commit_fn)
        books_file = load_books(data_dir / "books.json")
        if not any(b.id == book_id for b in books_file.books):
            comment_fn("Book id not found in your Readwise library.")
            close_fn()
            return

    highlights = sorted(
        client.get_highlights(book_id=book_id),
        key=lambda h: (h.location if h.location is not None else 10**9, h.id),
    )
    if not highlights:
        comment_fn("This book has no highlights.")
        close_fn()
        return

    snapshot = HighlightSnapshot(
        book_id=book_id,
        snapshotted_at=datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        highlights=highlights,
    )
    save_snapshot(snapshot, snapshot_path(data_dir, book_id))

    new_history = list(state.history)
    if state.current_book_id is not None and state.current_book_id != book_id:
        old_snap_path = snapshot_path(data_dir, state.current_book_id)
        old_count = len(load_snapshot(old_snap_path).highlights) if old_snap_path.exists() else 0
        new_history.append(HistoryEntry(
            book_id=state.current_book_id,
            started=state.current_book_started_on,
            finished=None,
            abandoned_at=now_chicago_date,
            position_at_abandon=state.position,
            highlight_count=old_count,
            outcome="abandoned",
        ))

    refresh_books_run(client=client, data_dir=data_dir, commit_fn=commit_fn)

    new_state = replace(
        state,
        current_book_id=book_id,
        current_book_started_on=now_chicago_date,
        position=0,
        picker_email_sent_on=None,
        history=new_history,
    )
    save_state(new_state, data_dir / "state.json")

    commit_fn(
        f"select: book {book_id} on {now_chicago_date.isoformat()}",
        ["data/state.json", f"data/highlights/{book_id}.json", "data/books.json"],
        None,
    )

    selected = next(b for b in books_file.books if b.id == book_id)
    comment_fn(
        f"Selected {selected.title} by {selected.author or '(unknown)'}. "
        f"{len(highlights)} highlights queued. "
        f"First batch arrives next weekday at 7am Chicago time."
    )
    close_fn()


def _make_gh_helpers(repo: str, issue_number: int) -> tuple[CommentFn, CloseFn]:
    def comment(body: str) -> None:
        subprocess.run(
            ["gh", "issue", "comment", str(issue_number), "--repo", repo, "--body", body],
            check=True,
        )

    def close() -> None:
        subprocess.run(
            ["gh", "issue", "close", str(issue_number), "--repo", repo],
            check=True,
        )

    return comment, close


def main() -> None:
    config = load_config("config.yaml")
    token = os.environ["READWISE_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    repo_owner = repo.split("/", 1)[0]

    event_path = os.environ["GITHUB_EVENT_PATH"]
    event = json.loads(Path(event_path).read_text())
    issue = event["issue"]

    client = ReadwiseClient(token=token)
    if not client.validate_token():
        raise SystemExit("Readwise token validation failed.")

    comment_fn, close_fn = _make_gh_helpers(repo, issue["number"])

    from zoneinfo import ZoneInfo
    today = datetime.now(tz=ZoneInfo(config.timezone)).date()

    run(
        issue_title=issue["title"],
        issue_user=issue["user"]["login"],
        issue_number=issue["number"],
        repo_owner=repo_owner,
        client=client,
        data_dir=Path("data"),
        commit_fn=commit_and_push,
        comment_fn=comment_fn,
        close_fn=close_fn,
        now_chicago_date=today,
    )


if __name__ == "__main__":
    main()
