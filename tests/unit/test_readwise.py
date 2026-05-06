"""Readwise HTTP client foundation: auth, pagination, retries."""

import pytest
import responses

from readwise_review.readwise import ReadwiseClient


def test_auth_header_set_on_request() -> None:
    client = ReadwiseClient(token="test-token")
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            "https://readwise.io/api/v2/auth/",
            status=204,
            match=[responses.matchers.header_matcher({"Authorization": "Token test-token"})],
        )
        client._get("https://readwise.io/api/v2/auth/")


def test_paged_get_yields_results_across_pages() -> None:
    client = ReadwiseClient(token="t")
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            "https://readwise.io/api/v2/books/",
            json={
                "count": 3,
                "next": "https://readwise.io/api/v2/books/?page=2",
                "previous": None,
                "results": [{"id": 1}, {"id": 2}],
            },
            status=200,
        )
        rsps.add(
            responses.GET,
            "https://readwise.io/api/v2/books/?page=2",
            json={"count": 3, "next": None, "previous": None, "results": [{"id": 3}]},
            status=200,
        )

        results = list(client._paged_get("https://readwise.io/api/v2/books/", params={"page_size": 1000}))

    assert [r["id"] for r in results] == [1, 2, 3]


def test_retry_on_429_uses_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("readwise_review.readwise.time.sleep", lambda s: sleeps.append(s))
    client = ReadwiseClient(token="t")
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            "https://example.com/",
            status=429,
            headers={"Retry-After": "3"},
        )
        rsps.add(responses.GET, "https://example.com/", json={"ok": True}, status=200)
        client._get("https://example.com/")
    assert sleeps == [3.0]


def test_retry_on_5xx_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("readwise_review.readwise.time.sleep", lambda s: sleeps.append(s))
    client = ReadwiseClient(token="t")
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://example.com/", status=503)
        rsps.add(responses.GET, "https://example.com/", status=503)
        rsps.add(responses.GET, "https://example.com/", json={"ok": True}, status=200)
        client._get("https://example.com/")
    assert sleeps == [1.0, 4.0]


def test_4xx_other_than_429_raises_immediately() -> None:
    client = ReadwiseClient(token="t")
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://example.com/", status=401, body="bad token")
        with pytest.raises(Exception) as ei:
            client._get("https://example.com/")
        assert "401" in str(ei.value) or "bad token" in str(ei.value)


def test_5xx_eventually_fails_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("readwise_review.readwise.time.sleep", lambda s: None)
    client = ReadwiseClient(token="t")
    with responses.RequestsMock() as rsps:
        for _ in range(4):
            rsps.add(responses.GET, "https://example.com/", status=500)
        with pytest.raises(Exception):
            client._get("https://example.com/")
