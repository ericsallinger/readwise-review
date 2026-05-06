"""Renders email subject, HTML body, and plain-text body for each template."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from jinja2 import Environment, PackageLoader, select_autoescape

from readwise_review.state import BookEntry, Highlight


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    plain: str


_LOCATION_LABELS = {
    "page": "p.",
    "location": "loc.",
    "order": "#",
    "offset": "@",
    "time_offset": "@",
}


def _format_location(location_type: str | None) -> str:
    return _LOCATION_LABELS.get(location_type or "", "@")


def _urlencode(s: str) -> str:
    """Encode string for use in URLs. Space becomes %20, not +."""
    return quote(s, safe="")


def _make_env() -> Environment:
    env = Environment(
        loader=PackageLoader("readwise_review", "templates"),
        autoescape=select_autoescape(["html"]),
        trim_blocks=False,
        lstrip_blocks=False,
    )
    env.filters["format_location"] = _format_location
    env.filters["urlencode"] = _urlencode
    return env


_env = _make_env()


def render_highlights_email(
    *,
    book: BookEntry,
    highlights: list[Highlight],
    position_start: int,
    total_in_book: int,
    is_finishing: bool,
    all_books: list[BookEntry],
    repo: str,
) -> RenderedEmail:
    position_end = position_start + len(highlights)
    remaining = total_in_book - position_end
    sorted_books = sorted(all_books, key=lambda b: b.title)
    ctx = {
        "book": book,
        "highlights": highlights,
        "position_start": position_start,
        "position_end": position_end,
        "total_in_book": total_in_book,
        "remaining": remaining,
        "is_finishing": is_finishing,
        "all_books": sorted_books,
        "repo": repo,
    }
    subject = f"Readwise: {book.title} — {position_start + 1}–{position_end} of {total_in_book}"
    html = _env.get_template("highlights.html.j2").render(**ctx)
    plain = _env.get_template("highlights.txt.j2").render(**ctx)
    return RenderedEmail(subject=subject, html=html, plain=plain)


def render_picker_email(*, books: list[BookEntry], repo: str) -> RenderedEmail:
    sorted_books = sorted(books, key=lambda b: b.title)
    ctx = {"books": sorted_books, "repo": repo}
    subject = "Readwise: pick a book to review"
    html = _env.get_template("picker.html.j2").render(**ctx)
    plain = _env.get_template("picker.txt.j2").render(**ctx)
    return RenderedEmail(subject=subject, html=html, plain=plain)
