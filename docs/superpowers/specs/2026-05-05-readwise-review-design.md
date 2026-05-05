# Readwise Highlight Review System — Design

**Date:** 2026-05-05
**Status:** Approved for implementation planning

## Goal

Build a daily-email habit system that helps the user review books they've read by surfacing highlights from their Readwise library. Each weekday morning at 7am America/Chicago time, an email arrives with a configurable number of highlights from the currently-selected book. When the book is exhausted, the same email contains a picker for choosing the next book.

## Non-goals

- Article, podcast, tweet, or supplemental highlight review (books only).
- Re-ordering or filtering highlights within a book (sequential by location only).
- Multi-user support; this is a single-user system.
- A web UI; interaction is via email and GitHub.
- Always-on availability; it is a once-per-weekday batch job.

## Decisions captured during brainstorming

| Decision | Choice |
|---|---|
| Hosting | GitHub Actions (cron + issue triggers) |
| Language | Python 3.12 |
| Email transport | Gmail SMTP with an app password |
| Send time | 7:00 America/Chicago, weekdays only |
| Scope | Books only |
| Highlight order | Sequential by Readwise `location` field |
| Highlight count per email | 8 by default, single config-file variable |
| Selection mechanism | Pre-filled GitHub issue links per book; `issues.opened` workflow updates state |
| End-of-book email | Same-day email contains final highlights AND book picker |
| No-current-book behavior | Send picker email once, then stay silent until selection |
| First-book bootstrap | `bootstrap_book_id` field in `config.yaml` |
| Re-selecting a finished book | Treated as fresh; position resets to 0 |
| Highlight delivery model | Snapshot on selection (frozen JSON file per book) |
| Formatting | No emojis; bold, underlines, line spacing for visual hierarchy |

## Architecture

Three GitHub Actions workflows in a single public repo, sharing a Python module under `src/readwise_review/`. State is persisted as JSON files committed back to the repo by the workflows; no external database.

### Workflows

1. **`daily-email.yml`** — fires at 12:00 UTC and 13:00 UTC on Mon–Fri (handles DST without drift) plus `workflow_dispatch` for manual testing. Each invocation gates on local Chicago hour == 7 before doing anything; only one of the two cron times passes that gate on any given day.

2. **`select-book.yml`** — fires on `issues: types: [opened]`. Filters by issue author (`== repository_owner`) and title prefix (`select-book:`). Parses the body for `book_id`, snapshots the book, updates state, comments on the issue with confirmation, and closes it.

3. **`refresh-books.yml`** — fires Sunday 12:00 UTC and `workflow_dispatch`. Refreshes `data/books.json` from the Readwise API. Also called inline from `select-book.yml` so the picker email always reflects the current library.

### Concurrency

Each workflow declares a `concurrency:` group keyed by the workflow name so two runs cannot race on the same state file. Push conflicts during commit are resolved by a single pull-rebase-retry; failure after that is loud.

### Timezone handling

All date and hour computations use Python's standard-library `zoneinfo.ZoneInfo("America/Chicago")` (Python 3.12). UTC is used for all `*_at` ISO timestamps; Chicago-local dates are used for all `*_on` and `*_date` fields and for the local-hour gate.

## Repo layout

```
.github/workflows/
  daily-email.yml
  select-book.yml
  refresh-books.yml
  tests.yml                    # runs unit tests on push and PR
src/readwise_review/
  __init__.py
  readwise.py                  # API client: list_books(), get_highlights(book_id)
  state.py                     # load/save state.json, books.json, highlights/<id>.json
  email_render.py              # Jinja2 templates: highlights, finishing, picker
  email_send.py                # Gmail SMTP wrapper (multipart HTML + plain text)
  daily.py                     # entrypoint: send daily email
  select.py                    # entrypoint: handle selection issue
  refresh.py                   # entrypoint: refresh books.json
config.yaml                    # user-editable settings
data/
  state.json                   # current book + position + history
  books.json                   # cached book list
  highlights/
    <book_id>.json             # frozen snapshot per selected book
tests/
  unit/                        # pytest, no network
  integration/                 # pytest, network, run with -m integration
pyproject.toml
README.md
```

## Readwise API integration

### Setup (one-time, by the user)

1. Visit `https://readwise.io/access_token` while signed in to Readwise.
2. Copy the access token shown on that page.
3. In the GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**, name `READWISE_TOKEN`, value = the token from step 2.

The token is sent on every API request as an HTTP header:

```
Authorization: Token <READWISE_TOKEN>
```

### Endpoints used

The system uses three Readwise API v2 endpoints. All return JSON; all require the `Authorization` header above.

**1. `GET /api/v2/auth/` — token validation**

Returns `204 No Content` if the token is valid; `401` otherwise. Used once at the start of every workflow run as a fail-fast check, so a bad/revoked token surfaces clearly in the workflow log instead of producing confusing downstream errors.

**2. `GET /api/v2/books/` — list books**

Used by `refresh.py` to populate `data/books.json`.

Query parameters we send:
- `category=books` — filter to the books category only (excludes articles, tweets, podcasts, supplementals).
- `page_size=1000` — the max. Most libraries fit in a single page.
- `page=N` — incremented while the response's `next` field is non-null.

Response fields we read from each item in `results[]`:

| Readwise field | Used as |
|---|---|
| `id` | `books[].id` in `data/books.json` |
| `title` | `books[].title` |
| `author` | `books[].author` (may be `null`; treat as empty string for rendering) |
| `num_highlights` | `books[].num_highlights`; we filter out books where this is `0` |

All other fields (`category`, `source`, `cover_image_url`, `tags`, etc.) are ignored.

**3. `GET /api/v2/highlights/` — list highlights for a book**

Used by `select.py` to snapshot all highlights for the just-selected book.

Query parameters we send:
- `book_id=<id>` — the selected book's id.
- `page_size=1000` — the max.
- `page=N` — incremented while the response's `next` is non-null.

Response fields we read from each item in `results[]`:

| Readwise field | Used as |
|---|---|
| `id` | `highlights[].id` in the snapshot file |
| `text` | `highlights[].text` |
| `location` | `highlights[].location` (integer, may be `null`) |
| `location_type` | `highlights[].location_type` (string, e.g., `"page"`, `"location"`, `"order"`) |
| `note` | `highlights[].note` (may be empty string) |
| `highlighted_at` | `highlights[].highlighted_at` (ISO 8601 string, may be `null`) |
| `book_id` | sanity-checked against the requested book id |

After fetching all pages, the highlights are sorted by `(location, id)`. Highlights with `location is null` are placed at the end, ordered by `id`, so the system never crashes on a book with missing location data.

### Why not `/api/v2/export/`?

The export endpoint is recommended for bulk sync and returns books + nested highlights in one response. It would conflate two concerns we want separate (refreshing the book list vs snapshotting one book's highlights), and it would re-fetch highlights for every book on every refresh. The narrower `/books/` and `/highlights/?book_id=X` endpoints match our access pattern: the book list is fetched weekly, and a book's highlights are fetched only when that book is selected.

### Pagination strategy

Both endpoints we use are offset-based with `next` URLs in the response. The client implements a simple loop:

```python
def paged_get(url, params):
    while url:
        response = http.get(url, headers=auth_headers(), params=params)
        response.raise_for_status()
        body = response.json()
        yield from body["results"]
        url = body["next"]
        params = None  # next URL already encodes its own params
```

### Rate limits and retry

Readwise's documented limits:
- 240 requests/minute per token in general
- 20 requests/minute for LIST endpoints (`/books/` and `/highlights/`)

Our access pattern stays comfortably under these:
- `refresh.py` makes 1–2 paged LIST calls per week (most libraries fit on one page).
- `select.py` makes 1–2 paged LIST calls per book selection (~weekly).
- `daily.py` makes zero Readwise calls in the highlights branch (snapshots are local), and only fires `refresh.py` inline on finishing days and picker days.

The HTTP client wraps each call with retry logic:
- On `429`: read the `Retry-After` header (seconds), sleep that long, retry once. If still `429`, fail.
- On `5xx`: exponential backoff, up to 3 attempts (1s, 4s, 16s).
- On other `4xx`: fail immediately and surface the response body in the workflow log.
- On network errors: retry up to 3 times with the same backoff as `5xx`.

### Failure surfaces

- **In `daily.py`**: Readwise failures only matter on finishing days and picker days (when an inline refresh is needed). The workflow exits non-zero, no email is sent, no state is changed; tomorrow's run will retry.
- **In `select.py`**: Readwise failure leaves the issue *open* with an error comment, so re-opening (or just commenting) does not need any rework — the user can wait and re-trigger by closing and reopening, or by submitting a fresh issue.
- **In `refresh.py`**: workflow fails loudly. Books.json is unchanged. The next scheduled refresh tries again.

## Configuration

`config.yaml` is the only user-editable runtime configuration:

```yaml
highlights_per_email: 8
to_email: eric.sallinger303@gmail.com
from_email: eric.sallinger303@gmail.com
bootstrap_book_id: null
timezone: America/Chicago
```

`bootstrap_book_id` lets the user seed the first book without going through a picker email. When set, the next daily run snapshots that book, sets it as `current_book_id`, clears `bootstrap_book_id` back to `null`, and proceeds normally.

## State schemas

### `data/state.json`

```json
{
  "current_book_id": 12345,
  "current_book_started_on": "2026-05-01",
  "position": 24,
  "last_send_date": "2026-05-04",
  "picker_email_sent_on": null,
  "bootstrap_consumed": true,
  "history": [
    {
      "book_id": 9876,
      "started": "2026-04-01",
      "finished": "2026-04-30",
      "highlight_count": 47,
      "outcome": "completed"
    },
    {
      "book_id": 5555,
      "started": "2026-03-15",
      "finished": null,
      "abandoned_at": "2026-04-01",
      "position_at_abandon": 12,
      "highlight_count": 60,
      "outcome": "abandoned"
    }
  ]
}
```

Fields:

- `current_book_id` — Readwise book id, or `null` between books.
- `current_book_started_on` — ISO date in Chicago timezone when the current book was selected. `null` when no current book.
- `position` — index of the next highlight to send within the snapshot. Range `[0, total_highlights]`. Equals `total_highlights` only momentarily before the finishing email rolls the book to history.
- `last_send_date` — ISO date in Chicago timezone of the most recent successful send. Used for daily-run idempotency.
- `picker_email_sent_on` — ISO date in Chicago timezone, or `null`. Set when a picker email is sent so it does not re-send daily. Cleared when a book is selected.
- `bootstrap_consumed` — boolean. Set to `true` after the daily script consumes `config.bootstrap_book_id` for the first time; prevents re-bootstrapping later when the user finishes a book and `current_book_id` returns to `null`.
- `history` — append-only log of cycles. Each entry has `outcome: "completed"` (with `finished` set, `abandoned_at: null`) or `outcome: "abandoned"` (with `finished: null`, `abandoned_at` and `position_at_abandon` set).

### `data/books.json`

```json
{
  "fetched_at": "2026-05-03T12:00:00Z",
  "books": [
    {
      "id": 12345,
      "title": "The Beginning of Infinity",
      "author": "David Deutsch",
      "num_highlights": 87
    }
  ]
}
```

Books are sorted alphabetically by title for stable diffs and stable picker-email ordering. Only books with at least one highlight are included.

### `data/highlights/<book_id>.json`

```json
{
  "book_id": 12345,
  "snapshotted_at": "2026-05-01T12:01:23Z",
  "highlights": [
    {
      "id": 555,
      "text": "...",
      "location": 42,
      "location_type": "page",
      "note": "...",
      "highlighted_at": "2024-08-12T14:23:00Z"
    }
  ]
}
```

Highlights are pre-sorted by `(location, id)` at snapshot time. The daily script slices `highlights[position : position + N]` without re-sorting.

## Daily-email logic (`daily.py`)

```
1. Load config.yaml and state.json.
2. Compute today_chicago.
3. If current Chicago hour != 7, exit 0 (the other cron time will fire later or did already).
4. If state.last_send_date == today_chicago, exit 0 (already sent today).
5. Branch:
   a. current_book_id is null AND config.bootstrap_book_id is set
      AND state.bootstrap_consumed is false:
      - Snapshot config.bootstrap_book_id (calls Readwise highlights API,
        sorts by (location, id), writes data/highlights/<id>.json).
      - Set current_book_id = bootstrap_book_id, current_book_started_on = today_chicago,
        position = 0, bootstrap_consumed = true.
      - Fall through to branch (d) (send first batch of highlights immediately).
   b. current_book_id is null AND picker_email_sent_on != null:
      - Exit 0 (user has not selected a book yet; we already prompted).
   c. current_book_id is null AND picker_email_sent_on is null:
      - Refresh books.json inline.
      - Render and send picker email.
      - Set picker_email_sent_on = today_chicago.
      - Set last_send_date = today_chicago.
      - Commit and exit.
   d. current_book_id is set:
      - Load highlights snapshot.
      - slice = highlights[position : position + N].
      - is_finishing = (position + len(slice) >= len(highlights)).
      - If is_finishing: refresh books.json inline (so picker section is fresh).
      - Render highlights email (finishing variant if is_finishing).
      - Send.
      - If is_finishing:
          push current book to history with outcome = "completed",
            started = current_book_started_on, finished = today_chicago,
            highlight_count = len(highlights).
          set current_book_id = null, current_book_started_on = null, position = 0.
          set picker_email_sent_on = today_chicago.
        else:
          position += len(slice).
      - Set last_send_date = today_chicago.
      - Commit and exit.
6. Any failure before commit: do not modify state. Exit non-zero so the workflow logs the failure.
```

## Selection logic (`select.py`)

```
0. Compute today_chicago.
1. Read GitHub event payload from $GITHUB_EVENT_PATH.
2. Validate issue.user.login == repository_owner. If not, exit 0 silently.
3. Validate issue.title startswith "select-book:". If not, exit 0 silently.
4. Parse book_id from title (format: "select-book: <id>"). On parse failure,
   comment "Could not parse book_id. Expected title format: select-book: <id>",
   close the issue, exit 0.
5. If state.current_book_id == book_id: comment "Already on this book.",
   close, exit 0. (Idempotency short-circuit before any API calls.)
6. Load books.json. If book_id not found, refresh books.json once and re-check.
   If still not found, comment "Book id not found in your Readwise library.",
   close, exit 0.
7. Fetch all highlights for book_id from Readwise. If 0 highlights, comment
   "This book has no highlights.", close, exit 0.
8. Sort by (location, id), write data/highlights/<book_id>.json.
9. If state.current_book_id is set and != book_id: push old book to history
   with outcome = "abandoned", started = current_book_started_on,
   finished = null, abandoned_at = today_chicago, position_at_abandon = position,
   highlight_count = (length of old book's snapshot).
10. Update state: current_book_id = book_id, current_book_started_on = today_chicago,
    position = 0, picker_email_sent_on = null.
11. Refresh books.json (so num_highlights is current for the new book).
12. Commit (state + new snapshot + maybe books.json).
13. Comment on the issue: "Selected <title> by <author>. <N> highlights queued.
    First batch arrives next weekday at 7am Chicago time."
14. Close the issue.
```

## Refresh logic (`refresh.py`)

```
1. Call Readwise list_books().
2. Filter to books with num_highlights >= 1.
3. Sort by title (case-insensitive).
4. Write data/books.json with fetched_at = utcnow().
5. Commit if changed.
```

## Email content

All emails are sent as multipart messages with both an HTML part and a plain-text fallback. Formatting uses bold, underlines, horizontal rules, and generous line spacing. No emojis anywhere in any template.

### Highlights email

- **Subject:** `Readwise: <Book Title> — <position+1>–<position+N> of <total>`
- **Body:**
  - Header: book title (bold) and author, then a horizontal rule.
  - For each highlight: highlight text rendered in a serif font with comfortable leading; below it, a small caption line `p. <location>` (or appropriate location-type label); if the highlight has a personal note, render it indented as a blockquote with a "Note:" label.
  - Each highlight separated from the next by extra vertical whitespace.
  - Footer line: `<position+N> of <total> — <total - position - N> remaining`.

### Finishing email

Same as the highlights email, with this section appended after the final highlight and a horizontal rule:

> **<u>You've finished</u> *<Book Title>*.**
>
> **Pick the next book to review:**
>
> - [The Beginning of Infinity — David Deutsch (87 highlights)](https://github.com/<owner>/<repo>/issues/new?title=select-book:%2012345)
> - [Antifragile — Nassim Taleb (54 highlights)](https://github.com/<owner>/<repo>/issues/new?title=select-book:%209876)
> - …

The link uses GitHub's pre-fill query parameters; the user clicks the title, GitHub opens `issues/new` with the issue title pre-populated, and the user clicks "Submit new issue" to fire the selection workflow.

Books are listed alphabetically by title. Each link is a single line. The list is the full library, not a curated subset.

### Picker-only email

Sent when there is no current book and no picker email has been sent yet. Subject: `Readwise: pick a book to review`. Body: a one-sentence intro followed by the same picker list as the finishing email.

## Idempotency invariants

- `daily.py` is a no-op if `last_send_date == today_chicago`.
- `select.py` is a no-op if the selected `book_id == current_book_id`.
- All state writes are atomic per workflow run; partial failures leave state unchanged.
- The same `book_id` selected twice never duplicates email; the second run sees `current_book_id == book_id` and exits.

## Edge case matrix

| Scenario | Handling |
|---|---|
| DST transition day | Two cron times (12:00 and 13:00 UTC) plus local-hour gate; exactly one fires year-round. |
| Manual `workflow_dispatch` on same day | `last_send_date == today_chicago` short-circuits; no double email. |
| Two daily runs racing | `concurrency:` block at workflow level serializes them. |
| Push conflict on state commit | Pull-rebase-retry once; if still conflicting, fail loudly. |
| Readwise API failure during daily run | Daily run still works for the highlights branch (snapshot is local). Picker branch fails loudly because it needs `refresh-books`. |
| Readwise API failure during selection | Issue is commented with the error and not closed; user can retry by re-opening. |
| SMTP failure | Workflow fails. State is not updated, so tomorrow's run sends the same highlights (resume-on-failure). |
| Snapshot empty (book has 0 highlights) | Selection rejects with comment, no state change. |
| User selects a book mid-cycle | New selection wins; old book pushed to `history` with `finished: null, abandoned_at, position_at_abandon`. |
| Issue submitted by someone else on a public repo | Job-level `if:` check skips it without modifying state. |
| Malformed issue title | Parser returns helpful error comment, closes issue, no state change. |
| Re-selecting a finished book | Treated as fresh: new snapshot, position resets to 0. |
| `books.json` stale when picker email rendered | Inline refresh runs before rendering picker emails. |
| 60-day repo inactivity pause | Daily commits keep the repo active; only triggers if user fully abandons the system. |
| Highlight `location` is null | Sort fallback: place null-location highlights at the end, ordered by `id`. |

## Secrets

| Name | Source | Purpose |
|---|---|---|
| `READWISE_TOKEN` | readwise.io/access_token | API access to user's library |
| `GMAIL_APP_PASSWORD` | Google account → Security → App passwords | SMTP auth |

The default `GITHUB_TOKEN` provided by GitHub Actions is sufficient for committing state and posting issue comments — no manual setup.

## Testing strategy

### Unit tests (no network, run on every push and PR)

- State load/save round-trips for `state.json`, `books.json`, and a highlights snapshot.
- `daily.py` decision tree with the Readwise client and SMTP mocked, covering: regular email, finishing email, picker email, picker-already-sent silence, bootstrap path, idempotent re-run.
- Issue title parser: valid, malformed, foreign book_id, already-current book_id.
- Email rendering: snapshot tests of rendered HTML for each template (catches accidental emoji creep and formatting regressions).
- Local-hour gate: parametrized over UTC times in CST and CDT windows.

### Integration tests (network, opt-in)

- Real Readwise API call fetching a small book and asserting shape.
- Real SMTP send to the `to_email` address with `[TEST]` subject.

### CI

- `tests.yml` runs the unit suite on every push and PR with Python 3.12.
- Integration tests are gated behind a `pytest -m integration` marker and run manually.

### Local dev affordances

- `daily.py --dry-run`: prints the would-send email to stdout instead of sending. Useful when triggering `workflow_dispatch` for verification.
- `refresh.py` can be run locally with `READWISE_TOKEN` in the environment to seed `data/books.json` before the first commit.

## One-time setup steps

1. `git init`; create the GitHub repo (public).
2. Generate a Gmail app password and a Readwise access token; add both as repo secrets.
3. Run `refresh.py` once locally to seed `data/books.json`.
4. Set `bootstrap_book_id` in `config.yaml` to the desired starting book.
5. Commit and push.
6. The first weekday at 7am Chicago, the first highlights email arrives.

## Open questions

None at the time of this writing. All major decisions captured above.
