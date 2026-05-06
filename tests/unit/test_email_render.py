"""Email rendering: subject + html + plain text for each template."""

import re

from readwise_review.email_render import (
    RenderedEmail,
    render_highlights_email,
    render_picker_email,
)
from readwise_review.state import BookEntry, Highlight


SAMPLE_HIGHLIGHTS = [
    Highlight(id=1, text="First quote.", location=10, location_type="page", note="",
              highlighted_at=None),
    Highlight(id=2, text="Second quote.", location=12, location_type="page",
              note="My note here.", highlighted_at=None),
]

SAMPLE_BOOKS = [
    BookEntry(id=42, title="Antifragile", author="Nassim Taleb", num_highlights=54),
    BookEntry(id=99, title="The Beginning of Infinity", author="David Deutsch", num_highlights=87),
]


def test_regular_highlights_email_subject_includes_range_and_title() -> None:
    email = render_highlights_email(
        book=BookEntry(id=42, title="Antifragile", author="Nassim Taleb", num_highlights=10),
        highlights=SAMPLE_HIGHLIGHTS,
        position_start=2,
        total_in_book=10,
        is_finishing=False,
        all_books=[],
        repo="user/repo",
    )
    assert email.subject == "Readwise: Antifragile — 3–4 of 10"


def test_regular_highlights_email_does_not_include_picker() -> None:
    email = render_highlights_email(
        book=BookEntry(id=42, title="Antifragile", author="Nassim Taleb", num_highlights=10),
        highlights=SAMPLE_HIGHLIGHTS,
        position_start=2,
        total_in_book=10,
        is_finishing=False,
        all_books=SAMPLE_BOOKS,
        repo="user/repo",
    )
    assert "Pick the next book" not in email.html
    assert "Pick the next book" not in email.plain


def test_finishing_email_includes_picker_with_alphabetical_books() -> None:
    email = render_highlights_email(
        book=BookEntry(id=42, title="Antifragile", author="Nassim Taleb", num_highlights=2),
        highlights=SAMPLE_HIGHLIGHTS,
        position_start=0,
        total_in_book=2,
        is_finishing=True,
        all_books=SAMPLE_BOOKS,
        repo="user/repo",
    )
    assert email.subject == "Readwise: Antifragile — 1–2 of 2"
    assert "Pick the next book" in email.html
    assert "You've finished" in email.html
    a_index = email.html.find("Antifragile")
    b_index = email.html.find("The Beginning of Infinity")
    assert a_index < b_index
    assert "https://github.com/user/repo/issues/new?title=select-book%3A%2042" in email.html
    assert "https://github.com/user/repo/issues/new?title=select-book%3A%2099" in email.html


def test_picker_only_email() -> None:
    email = render_picker_email(books=SAMPLE_BOOKS, repo="user/repo")
    assert email.subject == "Readwise: pick a book to review"
    assert "Pick the next book" in email.html
    assert "Antifragile" in email.html
    assert "The Beginning of Infinity" in email.html


def test_no_emojis_in_any_template() -> None:
    """No emoji characters should ever appear in rendered output."""
    emoji_re = re.compile(
        "[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001F000-\U0001F2FF]"
    )
    h_email = render_highlights_email(
        book=BookEntry(id=42, title="Antifragile", author="Nassim Taleb", num_highlights=2),
        highlights=SAMPLE_HIGHLIGHTS,
        position_start=0,
        total_in_book=2,
        is_finishing=True,
        all_books=SAMPLE_BOOKS,
        repo="user/repo",
    )
    p_email = render_picker_email(books=SAMPLE_BOOKS, repo="user/repo")
    for s in [h_email.html, h_email.plain, h_email.subject, p_email.html, p_email.plain, p_email.subject]:
        assert emoji_re.search(s) is None, f"emoji found in: {s[:200]}"


def test_highlight_with_note_renders_note_block() -> None:
    email = render_highlights_email(
        book=BookEntry(id=42, title="X", author="Y", num_highlights=2),
        highlights=SAMPLE_HIGHLIGHTS,
        position_start=0,
        total_in_book=2,
        is_finishing=False,
        all_books=[],
        repo="user/repo",
    )
    assert "My note here." in email.html
    assert "Note:" in email.html


def test_highlight_with_no_location_renders_no_caption() -> None:
    """Highlights with location=None should not render a 'p. None' or similar broken caption."""
    email = render_highlights_email(
        book=BookEntry(id=42, title="X", author="Y", num_highlights=1),
        highlights=[Highlight(id=1, text="t", location=None, location_type="page", note="", highlighted_at=None)],
        position_start=0,
        total_in_book=1,
        is_finishing=False,
        all_books=[],
        repo="user/repo",
    )
    assert "None" not in email.html


def test_picker_books_sorted_alphabetically_regardless_of_input_order() -> None:
    books_unsorted = [
        BookEntry(id=99, title="The Beginning of Infinity", author="David Deutsch", num_highlights=87),
        BookEntry(id=42, title="Antifragile", author="Nassim Taleb", num_highlights=54),
    ]
    email = render_picker_email(books=books_unsorted, repo="user/repo")
    a_index = email.html.find("Antifragile")
    b_index = email.html.find("The Beginning of Infinity")
    assert a_index < b_index
