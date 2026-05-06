"""Readwise API client: auth, pagination, retry logic."""

from __future__ import annotations

import time
from typing import Iterator

import requests


BASE_URL = "https://readwise.io/api/v2"


class ReadwiseClient:
    def __init__(self, token: str, *, base_url: str = BASE_URL, session: requests.Session | None = None) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Token {self._token}"}

    def _get(self, url: str, params: dict | None = None) -> requests.Response:
        """GET with retry for 429 (Retry-After) and 5xx (exponential backoff)."""
        backoffs = [1.0, 4.0, 16.0]
        five_xx_attempts = 0
        retried_429 = False
        while True:
            response = self._session.get(url, headers=self._headers(), params=params)
            if response.status_code == 429:
                if retried_429:
                    response.raise_for_status()
                wait = float(response.headers.get("Retry-After", "1"))
                time.sleep(wait)
                retried_429 = True
                continue
            if 500 <= response.status_code < 600:
                if five_xx_attempts >= len(backoffs):
                    response.raise_for_status()
                time.sleep(backoffs[five_xx_attempts])
                five_xx_attempts += 1
                continue
            if not response.ok:
                raise requests.HTTPError(
                    f"{response.status_code} from {url}: {response.text[:500]}",
                    response=response,
                )
            return response

    def _paged_get(self, url: str, params: dict | None = None) -> Iterator[dict]:
        """Iterate through paginated `results[]` across all pages."""
        next_url: str | None = url
        next_params = dict(params) if params else None
        while next_url:
            response = self._get(next_url, params=next_params)
            body = response.json()
            yield from body["results"]
            next_url = body.get("next")
            next_params = None

    def validate_token(self) -> bool:
        """Returns True if token is valid (HTTP 204), False on 401."""
        url = f"{self._base_url}/auth/"
        response = self._session.get(url, headers=self._headers())
        if response.status_code == 204:
            return True
        if response.status_code == 401:
            return False
        response.raise_for_status()
        return True

    def list_books(self) -> Iterator["BookEntry"]:
        """Yields all books in the user's library, category=books."""
        from readwise_review.state import BookEntry

        url = f"{self._base_url}/books/"
        for raw in self._paged_get(url, params={"category": "books", "page_size": 1000}):
            yield BookEntry(
                id=raw["id"],
                title=raw["title"],
                author=raw.get("author"),
                num_highlights=raw["num_highlights"],
            )

    def get_highlights(self, book_id: int) -> Iterator["Highlight"]:
        """Yields all highlights for the given book (unsorted; caller sorts)."""
        from readwise_review.state import Highlight

        url = f"{self._base_url}/highlights/"
        for raw in self._paged_get(url, params={"book_id": book_id, "page_size": 1000}):
            yield Highlight(
                id=raw["id"],
                text=raw["text"],
                location=raw.get("location"),
                location_type=raw.get("location_type", ""),
                note=raw.get("note", ""),
                highlighted_at=raw.get("highlighted_at"),
            )
