"""Daily email entrypoint: branches based on state to send highlights, finishing, or picker emails."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from readwise_review.config import Config, load_config
from readwise_review.email_send import send_email as real_send_email
from readwise_review.git_io import commit_and_push
from readwise_review.readwise import ReadwiseClient
from readwise_review.state import (
    State,
    load_books,
    load_state,
    save_state,
)


SendEmailFn = Callable[..., None]
CommitFn = Callable[[str, list[str], Path | None], bool]


def run(
    *,
    config: Config,
    data_dir: Path,
    client,
    send_email_fn: SendEmailFn,
    commit_fn: CommitFn,
    gmail_app_password: str,
    repo: str,
    now: datetime,
) -> None:
    """Single entrypoint for the daily-email logic. All collaborators are injected."""
    today = now.date()

    # Local-hour gate
    if now.hour != 7:
        return

    state = load_state(data_dir / "state.json")

    # Same-day idempotency
    if state.last_send_date == today:
        return

    # 5b. No current book, picker already sent → silence.
    if state.current_book_id is None and state.picker_email_sent_on is not None:
        return

    # 5c. No current book, no picker sent → send picker email.
    if state.current_book_id is None:
        from readwise_review.email_render import render_picker_email
        from readwise_review.refresh import run as refresh_books_run

        refresh_books_run(client=client, data_dir=data_dir, commit_fn=commit_fn)
        books_file = load_books(data_dir / "books.json")
        rendered = render_picker_email(books=books_file.books, repo=repo)
        send_email_fn(
            rendered,
            from_email=config.from_email,
            to_email=config.to_email,
            gmail_app_password=gmail_app_password,
        )
        new_state = replace(state, picker_email_sent_on=today, last_send_date=today)
        save_state(new_state, data_dir / "state.json")
        commit_fn(
            f"daily: send picker email for {today.isoformat()}",
            ["data/state.json", "data/books.json"],
            None,
        )
        return

    # 5d. Current book set → load snapshot, slice, send.
    from readwise_review.email_render import render_highlights_email
    from readwise_review.refresh import run as refresh_books_run
    from readwise_review.state import HistoryEntry, load_snapshot, snapshot_path

    snap = load_snapshot(snapshot_path(data_dir, state.current_book_id))
    n = config.highlights_per_email
    slice_ = snap.highlights[state.position : state.position + n]
    is_finishing = (state.position + len(slice_)) >= len(snap.highlights)

    books_file = load_books(data_dir / "books.json")
    if is_finishing:
        refresh_books_run(client=client, data_dir=data_dir, commit_fn=commit_fn)
        books_file = load_books(data_dir / "books.json")

    book_entry = next(b for b in books_file.books if b.id == state.current_book_id)
    rendered = render_highlights_email(
        book=book_entry,
        highlights=slice_,
        position_start=state.position,
        total_in_book=len(snap.highlights),
        is_finishing=is_finishing,
        all_books=books_file.books if is_finishing else [],
        repo=repo,
    )
    send_email_fn(
        rendered,
        from_email=config.from_email,
        to_email=config.to_email,
        gmail_app_password=gmail_app_password,
    )

    if is_finishing:
        history_entry = HistoryEntry(
            book_id=state.current_book_id,
            started=state.current_book_started_on,
            finished=today,
            abandoned_at=None,
            position_at_abandon=None,
            highlight_count=len(snap.highlights),
            outcome="completed",
        )
        new_state = replace(
            state,
            current_book_id=None,
            current_book_started_on=None,
            position=0,
            picker_email_sent_on=today,
            last_send_date=today,
            history=[*state.history, history_entry],
        )
        commit_msg = f"daily: finished book {state.current_book_id} on {today.isoformat()}"
    else:
        new_state = replace(
            state,
            position=state.position + len(slice_),
            last_send_date=today,
        )
        commit_msg = f"daily: send {len(slice_)} highlights for {today.isoformat()}"

    save_state(new_state, data_dir / "state.json")
    commit_fn(commit_msg, ["data/state.json", "data/books.json"], None)
    return


def main() -> None:
    config = load_config("config.yaml")
    token = os.environ["READWISE_TOKEN"]
    gmail_pw = os.environ["GMAIL_APP_PASSWORD"]
    repo = os.environ["GITHUB_REPOSITORY"]
    now = datetime.now(tz=ZoneInfo(config.timezone))
    client = ReadwiseClient(token=token)
    if not client.validate_token():
        raise SystemExit("Readwise token validation failed.")
    run(
        config=config,
        data_dir=Path("data"),
        client=client,
        send_email_fn=real_send_email,
        commit_fn=commit_and_push,
        gmail_app_password=gmail_pw,
        repo=repo,
        now=now,
    )


if __name__ == "__main__":
    main()
