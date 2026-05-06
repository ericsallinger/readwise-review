# readwise-review

Daily-email habit system that surfaces book highlights from your Readwise library each weekday morning. When a book is exhausted, the same email contains a picker for selecting the next book via a one-click GitHub issue.

The full design — architecture, workflows, state schemas, and the rationale behind every choice — lives in `docs/superpowers/specs/2026-05-05-readwise-review-design.md`.

## Setup

1. **Generate a Readwise token** at <https://readwise.io/access_token>. Add it to repo secrets as `READWISE_TOKEN`.
2. **Generate a Gmail app password** at <https://myaccount.google.com/apppasswords> (requires 2FA on the Google account). Add it to repo secrets as `GMAIL_APP_PASSWORD`.
3. **Seed the book list:** in the GitHub UI go to **Actions → Refresh books → Run workflow**. Verify `data/books.json` is populated with your library.
4. **Choose a starting book:** open `data/books.json`, copy the `id` of the book you want to start with, set it as `bootstrap_book_id` in `config.yaml`, commit, and push.
5. **Wait for 7am Chicago time on the next weekday.** The first highlights email will arrive.

## Daily flow

- Mon–Fri at 7am America/Chicago: highlights email arrives.
- When the current book is finished, the same morning's email contains a list of every book in your library. Click a title to start the next book — GitHub will pre-fill an issue; click "Submit." The selection workflow fires automatically and the next morning's email starts the new book.

## Local development

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -v
```

Integration tests (network) are gated behind `pytest -m integration`.

Made May 2026 using claude code ~4.5 various models + superpowers plugin