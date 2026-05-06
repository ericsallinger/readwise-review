"""Refresh data/books.json from the Readwise API."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from readwise_review.git_io import commit_and_push
from readwise_review.readwise import ReadwiseClient
from readwise_review.state import BooksFile, save_books


class _Clientish(Protocol):
    def list_books(self) -> "object": ...


CommitFn = Callable[[str, list[str], Path | None], bool]


def run(
    *,
    client: _Clientish,
    data_dir: Path,
    commit_fn: CommitFn = commit_and_push,
) -> None:
    """List books, write data/books.json, commit. `commit_fn` decides if a commit happens."""
    books = [b for b in client.list_books() if b.num_highlights >= 1]
    books.sort(key=lambda b: b.title.casefold())
    payload = BooksFile(
        fetched_at=datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        books=books,
    )
    save_books(payload, data_dir / "books.json")
    commit_fn("refresh: update books.json", ["data/books.json"], None)


def main() -> None:
    """CLI entrypoint."""
    token = os.environ["READWISE_TOKEN"]
    client = ReadwiseClient(token=token)
    if not client.validate_token():
        raise SystemExit("Readwise token validation failed (HTTP 401).")
    run(client=client, data_dir=Path("data"))


if __name__ == "__main__":
    main()
