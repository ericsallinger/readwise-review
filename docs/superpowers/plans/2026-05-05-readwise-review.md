# Readwise Highlight Review System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a daily-email habit system that emails the user a configurable number of book highlights from their Readwise library each weekday at 7am America/Chicago, with a GitHub-issue-based picker for selecting the next book once one is finished.

**Architecture:** Three GitHub Actions workflows (`daily-email`, `select-book`, `refresh-books`) drive a Python module under `src/readwise_review/`. State persists as JSON files committed back to the repo by the workflows; no external database. Authoritative design lives in `docs/superpowers/specs/2026-05-05-readwise-review-design.md` — read it before starting any task that touches design decisions.

**Tech Stack:** Python 3.12, `requests`, `jinja2`, `pyyaml`, `pytest`, `responses` (HTTP mocking), Gmail SMTP, GitHub Actions.

---

## File structure overview

Files created or modified across the plan, with one-line responsibility for each:

```
.github/workflows/
  tests.yml                          # CI: pytest on push/PR
  daily-email.yml                    # cron + workflow_dispatch
  select-book.yml                    # issues:opened
  refresh-books.yml                  # weekly cron + workflow_dispatch
src/readwise_review/
  __init__.py                        # version stamp; minimal
  config.py                          # load_config() — reads config.yaml
  state.py                           # dataclasses + load/save for state.json, books.json, snapshots
  git_io.py                          # commit_and_push() — shared workflow util
  readwise.py                        # ReadwiseClient: paged_get, list_books, get_highlights, validate_token
  email_render.py                    # render_highlights, render_picker (Jinja2)
  email_send.py                      # send_email() — Gmail SMTP wrapper
  templates/
    highlights.html.j2               # regular + finishing variant by flag
    highlights.txt.j2
    picker.html.j2
    picker.txt.j2
  daily.py                           # entrypoint: send daily email
  select.py                          # entrypoint: handle selection issue
  refresh.py                         # entrypoint: refresh books.json
config.yaml                          # user-editable settings (committed)
data/
  state.json                         # current book + position + history (seeded empty)
  books.json                         # cached book list (seeded empty)
  highlights/.gitkeep                # snapshot dir
tests/
  unit/                              # pytest, no network, default
  integration/                       # pytest, network, run with -m integration
pyproject.toml
.gitignore
README.md
```

**Conventions used in this plan:**
- **TDD throughout**: every code task writes the failing test first, runs it, implements, runs it green, then commits.
- **Inject `now`**: every entrypoint that needs the current time accepts `now: datetime | None = None` defaulting to `datetime.now(ZoneInfo("America/Chicago"))`. Tests pass an explicit datetime instead of patching the clock.
- **Inject collaborators**: `daily.run()`, `select.run()`, `refresh.run()` accept a `ReadwiseClient`-like and a `send_email`/`commit_fn` callable. Tests pass mocks; production wires the real ones.
- **No surprise bytes**: every test file using JSON, YAML, or HTML uses inline string fixtures rather than golden files unless the test is explicitly a snapshot test.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/readwise_review/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/unit/conftest.py`
- Create: `config.yaml`
- Create: `data/state.json`
- Create: `data/books.json`
- Create: `data/highlights/.gitkeep`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "readwise-review"
version = "0.1.0"
description = "Daily-email habit system for reviewing Readwise book highlights"
requires-python = ">=3.12"
dependencies = [
    "requests>=2.31",
    "jinja2>=3.1",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "responses>=0.24",
]

[project.scripts]
readwise-daily = "readwise_review.daily:main"
readwise-select = "readwise_review.select:main"
readwise-refresh = "readwise_review.refresh:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
readwise_review = ["templates/*.j2"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "integration: integration tests that hit live Readwise/SMTP (run with -m integration)",
]
addopts = "-m 'not integration'"
```

- [ ] **Step 2: Write `.gitignore`**

```
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.venv/
venv/
.env
*.egg-info/
build/
dist/
.coverage
.DS_Store
```

- [ ] **Step 3: Write `src/readwise_review/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: Write `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`**

Each is an empty file. Use the Write tool with empty content for each.

- [ ] **Step 5: Write `tests/unit/conftest.py`**

```python
"""Shared pytest fixtures for unit tests."""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


CHICAGO = ZoneInfo("America/Chicago")


@pytest.fixture
def chicago_7am() -> datetime:
    """A weekday morning at exactly 7:00 Chicago time, used as the canonical 'now' in tests."""
    return datetime(2026, 5, 6, 7, 0, 0, tzinfo=CHICAGO)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """A clean data directory with the standard layout (state.json, books.json, highlights/)."""
    d = tmp_path / "data"
    d.mkdir()
    (d / "state.json").write_text(json.dumps({
        "current_book_id": None,
        "current_book_started_on": None,
        "position": 0,
        "last_send_date": None,
        "picker_email_sent_on": None,
        "bootstrap_consumed": False,
        "history": [],
    }))
    (d / "books.json").write_text(json.dumps({
        "fetched_at": None,
        "books": [],
    }))
    (d / "highlights").mkdir()
    return d
```

- [ ] **Step 6: Write `config.yaml`**

```yaml
highlights_per_email: 8
to_email: eric.sallinger303@gmail.com
from_email: eric.sallinger303@gmail.com
bootstrap_book_id: null
timezone: America/Chicago
```

- [ ] **Step 7: Write `data/state.json`**

```json
{
  "current_book_id": null,
  "current_book_started_on": null,
  "position": 0,
  "last_send_date": null,
  "picker_email_sent_on": null,
  "bootstrap_consumed": false,
  "history": []
}
```

- [ ] **Step 8: Write `data/books.json`**

```json
{
  "fetched_at": null,
  "books": []
}
```

- [ ] **Step 9: Write `data/highlights/.gitkeep`**

Empty file.

- [ ] **Step 10: Verify the package installs**

Run: `cd /Users/ericsallinger/Code/readwise && python -m venv .venv && .venv/bin/pip install -e ".[dev]"`
Expected: install succeeds. Then `.venv/bin/pytest tests/` should report "no tests ran" with exit 5 (no tests collected) — which is fine for now.

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml .gitignore src/readwise_review/__init__.py tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py tests/unit/conftest.py config.yaml data/state.json data/books.json data/highlights/.gitkeep
git commit -m "scaffold: package layout, deps, initial state files"
```

---

### Task 2: Config module

**Files:**
- Create: `src/readwise_review/config.py`
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_config.py`:

```python
"""Config module loads and validates config.yaml."""

from pathlib import Path

import pytest
import yaml

from readwise_review.config import Config, load_config


def test_load_config_reads_all_fields(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.safe_dump({
        "highlights_per_email": 5,
        "to_email": "to@example.com",
        "from_email": "from@example.com",
        "bootstrap_book_id": 42,
        "timezone": "America/Chicago",
    }))

    cfg = load_config(cfg_file)

    assert cfg == Config(
        highlights_per_email=5,
        to_email="to@example.com",
        from_email="from@example.com",
        bootstrap_book_id=42,
        timezone="America/Chicago",
    )


def test_load_config_defaults_bootstrap_book_id_to_none(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.safe_dump({
        "highlights_per_email": 8,
        "to_email": "to@example.com",
        "from_email": "from@example.com",
        "timezone": "America/Chicago",
    }))

    cfg = load_config(cfg_file)

    assert cfg.bootstrap_book_id is None


def test_load_config_rejects_missing_required_field(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.safe_dump({
        "highlights_per_email": 8,
        # missing to_email
        "from_email": "from@example.com",
        "timezone": "America/Chicago",
    }))

    with pytest.raises(KeyError):
        load_config(cfg_file)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_config.py -v`
Expected: ImportError on `from readwise_review.config import ...`

- [ ] **Step 3: Write `src/readwise_review/config.py`**

```python
"""Loads and validates config.yaml."""

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Config:
    highlights_per_email: int
    to_email: str
    from_email: str
    timezone: str
    bootstrap_book_id: int | None = None


def load_config(path: Path | str = "config.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text())
    return Config(
        highlights_per_email=raw["highlights_per_email"],
        to_email=raw["to_email"],
        from_email=raw["from_email"],
        timezone=raw["timezone"],
        bootstrap_book_id=raw.get("bootstrap_book_id"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_config.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/readwise_review/config.py tests/unit/test_config.py
git commit -m "feat: config module with yaml loader and required-field validation"
```

---

### Task 3: State module

**Files:**
- Create: `src/readwise_review/state.py`
- Create: `tests/unit/test_state.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_state.py`:

```python
"""State module load/save for state.json, books.json, and highlight snapshots."""

import json
from datetime import date
from pathlib import Path

from readwise_review.state import (
    BookEntry,
    BooksFile,
    Highlight,
    HighlightSnapshot,
    HistoryEntry,
    State,
    load_books,
    load_snapshot,
    load_state,
    save_books,
    save_snapshot,
    save_state,
)


def test_state_round_trip(tmp_path: Path) -> None:
    state = State(
        current_book_id=12345,
        current_book_started_on=date(2026, 5, 1),
        position=24,
        last_send_date=date(2026, 5, 4),
        picker_email_sent_on=None,
        bootstrap_consumed=True,
        history=[
            HistoryEntry(
                book_id=9876,
                started=date(2026, 4, 1),
                finished=date(2026, 4, 30),
                abandoned_at=None,
                position_at_abandon=None,
                highlight_count=47,
                outcome="completed",
            ),
        ],
    )
    path = tmp_path / "state.json"
    save_state(state, path)

    loaded = load_state(path)

    assert loaded == state


def test_state_handles_null_dates(tmp_path: Path) -> None:
    state = State(
        current_book_id=None,
        current_book_started_on=None,
        position=0,
        last_send_date=None,
        picker_email_sent_on=None,
        bootstrap_consumed=False,
        history=[],
    )
    path = tmp_path / "state.json"
    save_state(state, path)

    loaded = load_state(path)

    assert loaded == state


def test_state_history_handles_abandoned_entries(tmp_path: Path) -> None:
    state = State(
        current_book_id=None,
        current_book_started_on=None,
        position=0,
        last_send_date=date(2026, 5, 4),
        picker_email_sent_on=date(2026, 5, 4),
        bootstrap_consumed=True,
        history=[
            HistoryEntry(
                book_id=5555,
                started=date(2026, 3, 15),
                finished=None,
                abandoned_at=date(2026, 4, 1),
                position_at_abandon=12,
                highlight_count=60,
                outcome="abandoned",
            ),
        ],
    )
    path = tmp_path / "state.json"
    save_state(state, path)
    loaded = load_state(path)
    assert loaded == state


def test_books_round_trip(tmp_path: Path) -> None:
    books = BooksFile(
        fetched_at="2026-05-03T12:00:00Z",
        books=[
            BookEntry(id=12345, title="The Beginning of Infinity", author="David Deutsch", num_highlights=87),
            BookEntry(id=9876, title="Antifragile", author="Nassim Taleb", num_highlights=54),
        ],
    )
    path = tmp_path / "books.json"
    save_books(books, path)

    assert load_books(path) == books


def test_books_handles_null_author(tmp_path: Path) -> None:
    books = BooksFile(
        fetched_at="2026-05-03T12:00:00Z",
        books=[BookEntry(id=1, title="Anonymous Book", author=None, num_highlights=3)],
    )
    path = tmp_path / "books.json"
    save_books(books, path)
    assert load_books(path) == books


def test_snapshot_round_trip(tmp_path: Path) -> None:
    snapshot = HighlightSnapshot(
        book_id=12345,
        snapshotted_at="2026-05-01T12:01:23Z",
        highlights=[
            Highlight(
                id=555,
                text="The fundamental belief...",
                location=42,
                location_type="page",
                note="Important",
                highlighted_at="2024-08-12T14:23:00Z",
            ),
            Highlight(
                id=556,
                text="Another quote.",
                location=None,
                location_type="page",
                note="",
                highlighted_at=None,
            ),
        ],
    )
    path = tmp_path / "snapshot.json"
    save_snapshot(snapshot, path)

    assert load_snapshot(path) == snapshot


def test_state_file_is_pretty_printed(tmp_path: Path) -> None:
    """Diffs in commits should be readable; state files are pretty-printed."""
    state = State(
        current_book_id=1,
        current_book_started_on=date(2026, 5, 1),
        position=0,
        last_send_date=None,
        picker_email_sent_on=None,
        bootstrap_consumed=False,
        history=[],
    )
    path = tmp_path / "state.json"
    save_state(state, path)
    raw = path.read_text()
    assert "\n  " in raw
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_state.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `src/readwise_review/state.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_state.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/readwise_review/state.py tests/unit/test_state.py
git commit -m "feat: state module with dataclasses and JSON round-trip for state, books, snapshots"
```

---

### Task 4: Git commit helper

**Files:**
- Create: `src/readwise_review/git_io.py`
- Create: `tests/unit/test_git_io.py`

This module wraps the git operations that the entrypoints use to commit state changes back to the repo. Tested against a real temporary git repo (no mocking — the subprocess interface is the contract).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_git_io.py`:

```python
"""Git commit helper tested against real temp git repos."""

import subprocess
from pathlib import Path

import pytest

from readwise_review.git_io import commit_and_push


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    return remote


@pytest.fixture
def working_repo(tmp_path: Path, bare_remote: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare_remote)], cwd=repo, check=True)
    (repo / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo, check=True, capture_output=True)
    return repo


def test_commit_and_push_commits_changed_files(working_repo: Path) -> None:
    target = working_repo / "data" / "state.json"
    target.parent.mkdir()
    target.write_text("{}")

    commit_and_push("update state", [str(target.relative_to(working_repo))], cwd=working_repo)

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=working_repo, check=True, capture_output=True, text=True
    ).stdout
    assert "update state" in log


def test_commit_and_push_is_noop_when_nothing_changed(working_repo: Path) -> None:
    """Calling with no actual changes should not produce a commit."""
    target = working_repo / "data" / "state.json"
    target.parent.mkdir()
    target.write_text("{}")
    commit_and_push("first", [str(target.relative_to(working_repo))], cwd=working_repo)
    commit_and_push("second", [str(target.relative_to(working_repo))], cwd=working_repo)

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=working_repo, check=True, capture_output=True, text=True
    ).stdout
    assert "second" not in log


def test_commit_and_push_pushes_to_remote(working_repo: Path, bare_remote: Path) -> None:
    target = working_repo / "data" / "state.json"
    target.parent.mkdir()
    target.write_text("{}")

    commit_and_push("update", [str(target.relative_to(working_repo))], cwd=working_repo)

    remote_log = subprocess.run(
        ["git", "log", "--oneline", "main"],
        cwd=bare_remote, check=True, capture_output=True, text=True,
    ).stdout
    assert "update" in remote_log
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_git_io.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `src/readwise_review/git_io.py`**

```python
"""Git operations used by entrypoints to persist state back to the repo."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def _ensure_identity(cwd: Path) -> None:
    """Idempotent: set git user.email/user.name if not already configured."""
    have_email = _run(["git", "config", "user.email"], cwd=cwd, check=False).returncode == 0
    have_name = _run(["git", "config", "user.name"], cwd=cwd, check=False).returncode == 0
    if not have_email:
        _run(["git", "config", "user.email", "actions@github.com"], cwd=cwd)
    if not have_name:
        _run(["git", "config", "user.name", "readwise-review-bot"], cwd=cwd)


def commit_and_push(message: str, files: list[str], cwd: Path | None = None) -> bool:
    """Stage `files`, commit with `message`, push. Returns True if a commit was made.

    Returns False (no-op) if there were no staged changes after `git add`.
    On push conflict, performs a single pull --rebase and retries push once.
    """
    cwd_path = cwd if cwd is not None else Path.cwd()
    _ensure_identity(cwd_path)
    _run(["git", "add", *files], cwd=cwd_path)
    diff_check = _run(["git", "diff", "--cached", "--quiet"], cwd=cwd_path, check=False)
    if diff_check.returncode == 0:
        return False
    _run(["git", "commit", "-m", message], cwd=cwd_path)
    push = _run(["git", "push"], cwd=cwd_path, check=False)
    if push.returncode != 0:
        _run(["git", "pull", "--rebase"], cwd=cwd_path)
        _run(["git", "push"], cwd=cwd_path)
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_git_io.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/readwise_review/git_io.py tests/unit/test_git_io.py
git commit -m "feat: git_io.commit_and_push with no-op detection and conflict retry"
```

---

### Task 5: Readwise HTTP foundation

**Files:**
- Create: `src/readwise_review/readwise.py`
- Create: `tests/unit/test_readwise.py`

This task implements the HTTP plumbing only: auth header, `_paged_get` generator, retry logic for 429/5xx. Endpoint methods come in Task 6.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_readwise.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_readwise.py -v`
Expected: ImportError on `ReadwiseClient`.

- [ ] **Step 3: Write `src/readwise_review/readwise.py` (foundation only — endpoint methods in Task 6)**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_readwise.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/readwise_review/readwise.py tests/unit/test_readwise.py
git commit -m "feat: ReadwiseClient HTTP foundation with paged_get and retry logic"
```

---

### Task 6: Readwise endpoint methods

**Files:**
- Modify: `src/readwise_review/readwise.py`
- Modify: `tests/unit/test_readwise.py`

Add `validate_token`, `list_books`, `get_highlights` methods on top of the foundation.

- [ ] **Step 1: Append failing tests to `tests/unit/test_readwise.py`**

```python
from readwise_review.state import BookEntry, Highlight


def test_validate_token_returns_true_on_204() -> None:
    client = ReadwiseClient(token="t")
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://readwise.io/api/v2/auth/", status=204)
        assert client.validate_token() is True


def test_validate_token_returns_false_on_401() -> None:
    client = ReadwiseClient(token="bad")
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://readwise.io/api/v2/auth/", status=401)
        assert client.validate_token() is False


def test_list_books_maps_fields_and_filters_to_books_category() -> None:
    client = ReadwiseClient(token="t")
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            "https://readwise.io/api/v2/books/",
            json={
                "count": 2,
                "next": None,
                "previous": None,
                "results": [
                    {
                        "id": 12345,
                        "title": "The Beginning of Infinity",
                        "author": "David Deutsch",
                        "num_highlights": 87,
                        "category": "books",
                    },
                    {
                        "id": 9876,
                        "title": "Untitled",
                        "author": None,
                        "num_highlights": 4,
                        "category": "books",
                    },
                ],
            },
            status=200,
        )
        books = list(client.list_books())
    assert books == [
        BookEntry(id=12345, title="The Beginning of Infinity", author="David Deutsch", num_highlights=87),
        BookEntry(id=9876, title="Untitled", author=None, num_highlights=4),
    ]


def test_get_highlights_for_book_maps_fields() -> None:
    client = ReadwiseClient(token="t")
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            "https://readwise.io/api/v2/highlights/",
            json={
                "count": 1,
                "next": None,
                "previous": None,
                "results": [
                    {
                        "id": 555,
                        "text": "Quote",
                        "location": 42,
                        "location_type": "page",
                        "note": "",
                        "highlighted_at": "2024-08-12T14:23:00Z",
                        "book_id": 12345,
                        "color": "yellow",
                        "url": None,
                    },
                ],
            },
            status=200,
        )
        highlights = list(client.get_highlights(book_id=12345))
    assert highlights == [
        Highlight(
            id=555,
            text="Quote",
            location=42,
            location_type="page",
            note="",
            highlighted_at="2024-08-12T14:23:00Z",
        ),
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_readwise.py -v`
Expected: AttributeError on `validate_token` / `list_books` / `get_highlights`.

- [ ] **Step 3: Add methods to the `ReadwiseClient` class in `src/readwise_review/readwise.py`**

Append these methods to the class body:

```python
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
```

The `BookEntry` and `Highlight` imports are inside the methods to avoid any potential circular-import surprises with `state.py`; if no circularity exists, you can promote them to top-level.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_readwise.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/readwise_review/readwise.py tests/unit/test_readwise.py
git commit -m "feat: list_books, get_highlights, validate_token on ReadwiseClient"
```

---

### Task 7: Email rendering

**Files:**
- Create: `src/readwise_review/templates/highlights.html.j2`
- Create: `src/readwise_review/templates/highlights.txt.j2`
- Create: `src/readwise_review/templates/picker.html.j2`
- Create: `src/readwise_review/templates/picker.txt.j2`
- Create: `src/readwise_review/email_render.py`
- Create: `tests/unit/test_email_render.py`

The `highlights` template handles both regular and finishing variants via a boolean flag. Picker is its own template (used standalone).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_email_render.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_email_render.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `src/readwise_review/templates/highlights.html.j2`**

```jinja
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  body { font-family: Georgia, serif; max-width: 640px; margin: 24px auto; padding: 0 16px; line-height: 1.6; color: #1a1a1a; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .author { color: #555; font-size: 14px; margin-bottom: 16px; }
  hr { border: none; border-top: 1px solid #ddd; margin: 24px 0; }
  .highlight { margin: 24px 0; }
  .highlight-text { font-size: 17px; }
  .caption { color: #777; font-size: 13px; margin-top: 8px; }
  .note { margin: 12px 0 0 16px; padding-left: 12px; border-left: 3px solid #ccc; color: #444; font-style: italic; font-size: 14px; }
  .note-label { font-style: normal; font-weight: bold; }
  .footer { color: #666; font-size: 13px; margin-top: 32px; }
  .picker { margin-top: 32px; }
  .picker h2 { font-size: 18px; }
  .picker ul { padding-left: 20px; line-height: 1.8; }
  .finished { font-size: 18px; margin: 24px 0; }
  .finished u { text-decoration: underline; }
</style>
</head>
<body>
<h1>{{ book.title }}</h1>
<div class="author">{{ book.author or "" }}</div>
<hr>
{% for h in highlights %}
<div class="highlight">
  <div class="highlight-text">{{ h.text }}</div>
  {% if h.location is not none %}
  <div class="caption">{{ h.location_type | format_location }} {{ h.location }}</div>
  {% endif %}
  {% if h.note %}
  <div class="note"><span class="note-label">Note:</span> {{ h.note }}</div>
  {% endif %}
</div>
{% endfor %}
<div class="footer">{{ position_end }} of {{ total_in_book }} &mdash; {{ remaining }} remaining</div>
{% if is_finishing %}
<hr>
<div class="finished"><strong><u>You've finished</u> <em>{{ book.title }}</em>.</strong></div>
<div class="picker">
  <h2><strong>Pick the next book to review:</strong></h2>
  <ul>
  {% for b in all_books %}
    <li><a href="https://github.com/{{ repo }}/issues/new?title={{ ('select-book: ' ~ b.id) | urlencode }}">{{ b.title }} &mdash; {{ b.author or "" }} ({{ b.num_highlights }} highlights)</a></li>
  {% endfor %}
  </ul>
</div>
{% endif %}
</body>
</html>
```

- [ ] **Step 4: Write `src/readwise_review/templates/highlights.txt.j2`**

```jinja
{{ book.title }}
{{ book.author or "" }}
{% for h in highlights %}
---

{{ h.text }}
{% if h.location is not none %}
[{{ h.location_type | format_location }} {{ h.location }}]
{% endif %}
{% if h.note %}
Note: {{ h.note }}
{% endif %}
{% endfor %}
---

{{ position_end }} of {{ total_in_book }} -- {{ remaining }} remaining
{% if is_finishing %}

You've finished {{ book.title }}.

Pick the next book to review:
{% for b in all_books %}
- {{ b.title }} -- {{ b.author or "" }} ({{ b.num_highlights }} highlights)
  https://github.com/{{ repo }}/issues/new?title={{ ('select-book: ' ~ b.id) | urlencode }}
{% endfor %}
{% endif %}
```

- [ ] **Step 5: Write `src/readwise_review/templates/picker.html.j2`**

```jinja
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  body { font-family: Georgia, serif; max-width: 640px; margin: 24px auto; padding: 0 16px; line-height: 1.6; color: #1a1a1a; }
  h2 { font-size: 18px; }
  ul { padding-left: 20px; line-height: 1.8; }
  p { font-size: 16px; }
</style>
</head>
<body>
<p>Time to <strong>pick a book</strong> to review. Click any title to start a new cycle.</p>
<h2><strong>Pick the next book to review:</strong></h2>
<ul>
{% for b in books %}
  <li><a href="https://github.com/{{ repo }}/issues/new?title={{ ('select-book: ' ~ b.id) | urlencode }}">{{ b.title }} &mdash; {{ b.author or "" }} ({{ b.num_highlights }} highlights)</a></li>
{% endfor %}
</ul>
</body>
</html>
```

- [ ] **Step 6: Write `src/readwise_review/templates/picker.txt.j2`**

```jinja
Time to pick a book to review. Click any link to start a new cycle.

Pick the next book to review:
{% for b in books %}
- {{ b.title }} -- {{ b.author or "" }} ({{ b.num_highlights }} highlights)
  https://github.com/{{ repo }}/issues/new?title={{ ('select-book: ' ~ b.id) | urlencode }}
{% endfor %}
```

- [ ] **Step 7: Write `src/readwise_review/email_render.py`**

```python
"""Renders email subject, HTML body, and plain-text body for each template."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus

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


def _make_env() -> Environment:
    env = Environment(
        loader=PackageLoader("readwise_review", "templates"),
        autoescape=select_autoescape(["html"]),
        trim_blocks=False,
        lstrip_blocks=False,
    )
    env.filters["format_location"] = _format_location
    env.filters["urlencode"] = quote_plus
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
    ctx = {
        "book": book,
        "highlights": highlights,
        "position_start": position_start,
        "position_end": position_end,
        "total_in_book": total_in_book,
        "remaining": remaining,
        "is_finishing": is_finishing,
        "all_books": all_books,
        "repo": repo,
    }
    subject = f"Readwise: {book.title} — {position_start + 1}–{position_end} of {total_in_book}"
    html = _env.get_template("highlights.html.j2").render(**ctx)
    plain = _env.get_template("highlights.txt.j2").render(**ctx)
    return RenderedEmail(subject=subject, html=html, plain=plain)


def render_picker_email(*, books: list[BookEntry], repo: str) -> RenderedEmail:
    ctx = {"books": books, "repo": repo}
    subject = "Readwise: pick a book to review"
    html = _env.get_template("picker.html.j2").render(**ctx)
    plain = _env.get_template("picker.txt.j2").render(**ctx)
    return RenderedEmail(subject=subject, html=html, plain=plain)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_email_render.py -v`
Expected: 7 passed.

- [ ] **Step 9: Commit**

```bash
git add src/readwise_review/templates/ src/readwise_review/email_render.py tests/unit/test_email_render.py
git commit -m "feat: email rendering with Jinja2 templates for highlights, finishing, picker"
```

---

### Task 8: Email sending

**Files:**
- Create: `src/readwise_review/email_send.py`
- Create: `tests/unit/test_email_send.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_email_send.py`:

```python
"""Email sending: Gmail SMTP, multipart message, mocked smtplib."""

from email.message import EmailMessage
from unittest.mock import MagicMock, patch

from readwise_review.email_render import RenderedEmail
from readwise_review.email_send import send_email


def test_send_email_constructs_multipart_message_and_uses_ssl_smtp() -> None:
    rendered = RenderedEmail(subject="hello", html="<p>hi</p>", plain="hi")

    with patch("readwise_review.email_send.smtplib.SMTP_SSL") as smtp_cls:
        smtp = MagicMock()
        smtp_cls.return_value.__enter__.return_value = smtp
        send_email(
            rendered,
            from_email="from@example.com",
            to_email="to@example.com",
            gmail_app_password="pw",
        )

    smtp_cls.assert_called_once_with("smtp.gmail.com", 465)
    smtp.login.assert_called_once_with("from@example.com", "pw")
    smtp.send_message.assert_called_once()

    sent_msg: EmailMessage = smtp.send_message.call_args.args[0]
    assert sent_msg["Subject"] == "hello"
    assert sent_msg["From"] == "from@example.com"
    assert sent_msg["To"] == "to@example.com"
    assert sent_msg.is_multipart()
    parts = list(sent_msg.iter_parts())
    plain = next(p for p in parts if p.get_content_type() == "text/plain")
    html = next(p for p in parts if p.get_content_type() == "text/html")
    assert plain.get_content().strip() == "hi"
    assert html.get_content().strip() == "<p>hi</p>"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_email_send.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `src/readwise_review/email_send.py`**

```python
"""Send a RenderedEmail via Gmail SMTP."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from readwise_review.email_render import RenderedEmail


def send_email(
    rendered: RenderedEmail,
    *,
    from_email: str,
    to_email: str,
    gmail_app_password: str,
) -> None:
    msg = EmailMessage()
    msg["Subject"] = rendered.subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(rendered.plain)
    msg.add_alternative(rendered.html, subtype="html")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(from_email, gmail_app_password)
        smtp.send_message(msg)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_email_send.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/readwise_review/email_send.py tests/unit/test_email_send.py
git commit -m "feat: email_send.send_email Gmail SMTP wrapper with multipart message"
```

---

### Task 9: Refresh entrypoint

**Files:**
- Create: `src/readwise_review/refresh.py`
- Create: `tests/unit/test_refresh.py`

`refresh.py` is the simplest entrypoint: list books, sort, write `data/books.json`, commit.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_refresh.py`:

```python
"""Refresh entrypoint: writes books.json from Readwise list_books()."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from readwise_review.refresh import run as run_refresh
from readwise_review.state import BookEntry


def test_refresh_writes_only_books_with_highlights_sorted_by_title(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "books.json").write_text(json.dumps({"fetched_at": None, "books": []}))

    client = MagicMock()
    client.list_books.return_value = iter([
        BookEntry(id=1, title="Zebra", author=None, num_highlights=5),
        BookEntry(id=2, title="Apple", author="A", num_highlights=0),
        BookEntry(id=3, title="middle", author="B", num_highlights=2),
    ])

    committed: list[tuple[str, list[str]]] = []
    def fake_commit(msg, files, cwd=None):
        committed.append((msg, files))
        return True

    run_refresh(
        client=client,
        data_dir=data,
        commit_fn=fake_commit,
    )

    raw = json.loads((data / "books.json").read_text())
    assert [b["id"] for b in raw["books"]] == [3, 1]
    assert raw["fetched_at"] is not None
    assert committed and committed[0][1] == ["data/books.json"]


def test_refresh_invokes_commit_fn_even_when_only_fetched_at_changed(tmp_path: Path) -> None:
    """commit_fn is responsible for diffing; refresh always asks it to commit."""
    data = tmp_path / "data"
    data.mkdir()
    initial = {
        "fetched_at": "2026-04-01T00:00:00Z",
        "books": [{"id": 1, "title": "Same", "author": "A", "num_highlights": 3}],
    }
    (data / "books.json").write_text(json.dumps(initial, indent=2) + "\n")

    client = MagicMock()
    client.list_books.return_value = iter([
        BookEntry(id=1, title="Same", author="A", num_highlights=3),
    ])

    commit_called: list[str] = []
    def fake_commit(msg, files, cwd=None):
        commit_called.append(msg)
        return True

    run_refresh(
        client=client,
        data_dir=data,
        commit_fn=fake_commit,
    )

    assert commit_called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_refresh.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `src/readwise_review/refresh.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_refresh.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/readwise_review/refresh.py tests/unit/test_refresh.py
git commit -m "feat: refresh entrypoint to fetch and commit books.json"
```

---

### Task 10: Daily entrypoint — gating

**Files:**
- Create: `src/readwise_review/daily.py`
- Create: `tests/unit/test_daily.py`

The daily entrypoint is built across Tasks 10–13. This task implements only the local-hour gate and same-day idempotency check, plus the test infrastructure (mocks, fixtures) the later tasks build on.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_daily.py`:

```python
"""Daily entrypoint: gating, branching, state persistence."""

from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from readwise_review.config import Config
from readwise_review.daily import run as run_daily
from readwise_review.state import (
    BookEntry,
    BooksFile,
    Highlight,
    HighlightSnapshot,
    State,
    load_state,
    save_books,
    save_snapshot,
    save_state,
)


CHICAGO = ZoneInfo("America/Chicago")


@pytest.fixture
def config() -> Config:
    return Config(
        highlights_per_email=8,
        to_email="to@example.com",
        from_email="from@example.com",
        timezone="America/Chicago",
        bootstrap_book_id=None,
    )


@pytest.fixture
def empty_state() -> State:
    return State(
        current_book_id=None,
        current_book_started_on=None,
        position=0,
        last_send_date=None,
        picker_email_sent_on=None,
        bootstrap_consumed=False,
        history=[],
    )


@pytest.fixture
def data_dir_with_state(tmp_path: Path, empty_state: State) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    save_state(empty_state, d / "state.json")
    save_books(BooksFile(fetched_at=None, books=[]), d / "books.json")
    (d / "highlights").mkdir()
    return d


@pytest.fixture
def email_sent() -> list:
    return []


@pytest.fixture
def send_email_fake(email_sent):
    def _fake(rendered, *, from_email, to_email, gmail_app_password):
        email_sent.append({
            "subject": rendered.subject,
            "html": rendered.html,
            "plain": rendered.plain,
            "from_email": from_email,
            "to_email": to_email,
        })
    return _fake


@pytest.fixture
def commit_fn_fake():
    def _fake(message: str, files: list[str], cwd: Path | None = None) -> bool:
        return True
    return _fake


def _seven_am(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 7, 0, 0, tzinfo=CHICAGO)


def _eight_am(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 8, 0, 0, tzinfo=CHICAGO)


def test_skip_if_not_seven_am(
    config, data_dir_with_state, email_sent, send_email_fake, commit_fn_fake
):
    run_daily(
        config=config,
        data_dir=data_dir_with_state,
        client=MagicMock(),
        send_email_fn=send_email_fake,
        commit_fn=commit_fn_fake,
        gmail_app_password="pw",
        repo="user/repo",
        now=_eight_am(date(2026, 5, 6)),
    )
    assert email_sent == []


def test_skip_if_already_sent_today(
    config, tmp_path, email_sent, send_email_fake, commit_fn_fake
):
    today = date(2026, 5, 6)
    state = State(
        current_book_id=None,
        current_book_started_on=None,
        position=0,
        last_send_date=today,
        picker_email_sent_on=today,
        bootstrap_consumed=False,
        history=[],
    )
    d = tmp_path / "data"
    d.mkdir()
    save_state(state, d / "state.json")
    save_books(BooksFile(fetched_at=None, books=[]), d / "books.json")
    (d / "highlights").mkdir()

    run_daily(
        config=config,
        data_dir=d,
        client=MagicMock(),
        send_email_fn=send_email_fake,
        commit_fn=commit_fn_fake,
        gmail_app_password="pw",
        repo="user/repo",
        now=_seven_am(today),
    )
    assert email_sent == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_daily.py -v`
Expected: ImportError on `daily.run`.

- [ ] **Step 3: Write `src/readwise_review/daily.py`**

```python
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

    # Branches a/b/c/d come in subsequent tasks.
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_daily.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/readwise_review/daily.py tests/unit/test_daily.py
git commit -m "feat: daily entrypoint skeleton with hour gate and same-day idempotency"
```

---

### Task 11: Daily entrypoint — picker / silence branches

**Files:**
- Modify: `src/readwise_review/daily.py`
- Modify: `tests/unit/test_daily.py`

Implements branches **(b)** silence and **(c)** picker email.

- [ ] **Step 1: Append failing tests to `tests/unit/test_daily.py`**

```python
def test_picker_email_when_no_book_and_no_picker_sent(
    config, data_dir_with_state, email_sent, send_email_fake, commit_fn_fake
):
    today = date(2026, 5, 6)
    client = MagicMock()
    client.list_books.return_value = iter([
        BookEntry(id=42, title="Antifragile", author="Nassim Taleb", num_highlights=10),
        BookEntry(id=99, title="Beginning of Infinity", author="David Deutsch", num_highlights=20),
    ])

    run_daily(
        config=config,
        data_dir=data_dir_with_state,
        client=client,
        send_email_fn=send_email_fake,
        commit_fn=commit_fn_fake,
        gmail_app_password="pw",
        repo="user/repo",
        now=_seven_am(today),
    )

    assert len(email_sent) == 1
    assert email_sent[0]["subject"] == "Readwise: pick a book to review"
    s = load_state(data_dir_with_state / "state.json")
    assert s.picker_email_sent_on == today
    assert s.last_send_date == today


def test_silence_when_no_book_and_picker_already_sent(
    config, tmp_path, email_sent, send_email_fake, commit_fn_fake
):
    today = date(2026, 5, 6)
    state = State(
        current_book_id=None,
        current_book_started_on=None,
        position=0,
        last_send_date=date(2026, 5, 4),
        picker_email_sent_on=date(2026, 5, 4),
        bootstrap_consumed=False,
        history=[],
    )
    d = tmp_path / "data"
    d.mkdir()
    save_state(state, d / "state.json")
    save_books(BooksFile(fetched_at=None, books=[]), d / "books.json")
    (d / "highlights").mkdir()

    run_daily(
        config=config,
        data_dir=d,
        client=MagicMock(),
        send_email_fn=send_email_fake,
        commit_fn=commit_fn_fake,
        gmail_app_password="pw",
        repo="user/repo",
        now=_seven_am(today),
    )

    assert email_sent == []
    s = load_state(d / "state.json")
    assert s.last_send_date == date(2026, 5, 4)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_daily.py -v`
Expected: 2 new failures.

- [ ] **Step 3: Implement branches (b) and (c) in `src/readwise_review/daily.py`**

Replace the `# Branches a/b/c/d come in subsequent tasks.` comment with:

```python
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

    # 5d. Current book set → highlights / finishing branch (next task)
```

- [ ] **Step 4: Run all daily tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_daily.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/readwise_review/daily.py tests/unit/test_daily.py
git commit -m "feat: daily picker and silence branches"
```

---

### Task 12: Daily entrypoint — highlights / finishing branches + failure-resume

**Files:**
- Modify: `src/readwise_review/daily.py`
- Modify: `tests/unit/test_daily.py`

Implements branch **(d)** with both regular and finishing variants, plus the SMTP-failure-leaves-state-unchanged guarantee.

- [ ] **Step 1: Append failing tests to `tests/unit/test_daily.py`**

```python
def _seed_book_with_highlights(
    data_dir: Path, book_id: int, count: int, position: int = 0
) -> None:
    today = date(2026, 5, 1)
    state = State(
        current_book_id=book_id,
        current_book_started_on=today,
        position=position,
        last_send_date=None,
        picker_email_sent_on=None,
        bootstrap_consumed=True,
        history=[],
    )
    save_state(state, data_dir / "state.json")
    snap = HighlightSnapshot(
        book_id=book_id,
        snapshotted_at="2026-05-01T12:00:00Z",
        highlights=[
            Highlight(id=i, text=f"Quote {i}", location=i, location_type="page", note="", highlighted_at=None)
            for i in range(count)
        ],
    )
    save_snapshot(snap, data_dir / "highlights" / f"{book_id}.json")
    save_books(BooksFile(
        fetched_at="2026-05-01T12:00:00Z",
        books=[BookEntry(id=book_id, title="My Book", author="Author", num_highlights=count)],
    ), data_dir / "books.json")


def test_regular_highlights_email(
    config, tmp_path, email_sent, send_email_fake, commit_fn_fake
):
    today = date(2026, 5, 6)
    d = tmp_path / "data"
    d.mkdir()
    (d / "highlights").mkdir()
    _seed_book_with_highlights(d, book_id=42, count=20, position=4)

    run_daily(
        config=config,
        data_dir=d,
        client=MagicMock(),
        send_email_fn=send_email_fake,
        commit_fn=commit_fn_fake,
        gmail_app_password="pw",
        repo="user/repo",
        now=_seven_am(today),
    )

    assert len(email_sent) == 1
    assert email_sent[0]["subject"] == "Readwise: My Book — 5–12 of 20"
    assert "Pick the next book" not in email_sent[0]["html"]

    s = load_state(d / "state.json")
    assert s.position == 12
    assert s.last_send_date == today


def test_finishing_email_when_remaining_fits_in_one_email(
    config, tmp_path, email_sent, send_email_fake, commit_fn_fake
):
    today = date(2026, 5, 6)
    d = tmp_path / "data"
    d.mkdir()
    (d / "highlights").mkdir()
    _seed_book_with_highlights(d, book_id=42, count=10, position=6)
    save_books(BooksFile(
        fetched_at="2026-05-01T12:00:00Z",
        books=[
            BookEntry(id=42, title="My Book", author="Author", num_highlights=10),
            BookEntry(id=99, title="Other Book", author="Other Author", num_highlights=20),
        ],
    ), d / "books.json")

    client = MagicMock()
    client.list_books.return_value = iter([
        BookEntry(id=42, title="My Book", author="Author", num_highlights=10),
        BookEntry(id=99, title="Other Book", author="Other Author", num_highlights=20),
    ])

    run_daily(
        config=config,
        data_dir=d,
        client=client,
        send_email_fn=send_email_fake,
        commit_fn=commit_fn_fake,
        gmail_app_password="pw",
        repo="user/repo",
        now=_seven_am(today),
    )

    assert len(email_sent) == 1
    assert email_sent[0]["subject"] == "Readwise: My Book — 7–10 of 10"
    assert "Pick the next book" in email_sent[0]["html"]
    assert "You've finished" in email_sent[0]["html"]

    s = load_state(d / "state.json")
    assert s.current_book_id is None
    assert s.current_book_started_on is None
    assert s.position == 0
    assert s.picker_email_sent_on == today
    assert s.last_send_date == today
    assert len(s.history) == 1
    assert s.history[0].book_id == 42
    assert s.history[0].finished == today
    assert s.history[0].outcome == "completed"
    assert s.history[0].highlight_count == 10


def test_smtp_failure_leaves_state_unchanged(
    config, tmp_path, commit_fn_fake
):
    today = date(2026, 5, 6)
    d = tmp_path / "data"
    d.mkdir()
    (d / "highlights").mkdir()
    _seed_book_with_highlights(d, book_id=42, count=20, position=4)
    state_before = load_state(d / "state.json")

    def failing_send(*args, **kwargs):
        raise RuntimeError("SMTP down")

    with pytest.raises(RuntimeError):
        run_daily(
            config=config,
            data_dir=d,
            client=MagicMock(),
            send_email_fn=failing_send,
            commit_fn=commit_fn_fake,
            gmail_app_password="pw",
            repo="user/repo",
            now=_seven_am(today),
        )

    state_after = load_state(d / "state.json")
    assert state_after == state_before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_daily.py -v`
Expected: 3 new failures.

- [ ] **Step 3: Implement branch (d) in `src/readwise_review/daily.py`**

Replace the `# 5d. Current book set → highlights / finishing branch (next task)` comment with:

```python
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
```

The SMTP-failure invariant is maintained because `save_state` is called only after `send_email_fn` returns successfully. If `send_email_fn` raises, state on disk is unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_daily.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/readwise_review/daily.py tests/unit/test_daily.py
git commit -m "feat: daily highlights + finishing branches with state rollover"
```

---

### Task 13: Daily entrypoint — bootstrap branch

**Files:**
- Modify: `src/readwise_review/daily.py`
- Modify: `tests/unit/test_daily.py`

Implements branch **(a)**: bootstrap from `config.bootstrap_book_id` when no current book and not yet consumed. After bootstrapping, falls through to branch (d).

- [ ] **Step 1: Append failing test**

```python
def test_bootstrap_path_snapshots_book_and_sends_first_highlights(
    tmp_path, email_sent, send_email_fake, commit_fn_fake
):
    today = date(2026, 5, 6)
    config = Config(
        highlights_per_email=8,
        to_email="to@example.com",
        from_email="from@example.com",
        timezone="America/Chicago",
        bootstrap_book_id=42,
    )
    d = tmp_path / "data"
    d.mkdir()
    (d / "highlights").mkdir()
    save_state(State(
        current_book_id=None,
        current_book_started_on=None,
        position=0,
        last_send_date=None,
        picker_email_sent_on=None,
        bootstrap_consumed=False,
        history=[],
    ), d / "state.json")
    save_books(BooksFile(
        fetched_at="2026-05-01T12:00:00Z",
        books=[BookEntry(id=42, title="Bootstrap Book", author="Author", num_highlights=20)],
    ), d / "books.json")

    client = MagicMock()
    client.get_highlights.return_value = iter([
        Highlight(id=i, text=f"Quote {i}", location=i, location_type="page", note="", highlighted_at=None)
        for i in range(20)
    ])

    run_daily(
        config=config,
        data_dir=d,
        client=client,
        send_email_fn=send_email_fake,
        commit_fn=commit_fn_fake,
        gmail_app_password="pw",
        repo="user/repo",
        now=_seven_am(today),
    )

    snap_path = d / "highlights" / "42.json"
    assert snap_path.exists()
    assert len(email_sent) == 1
    assert email_sent[0]["subject"] == "Readwise: Bootstrap Book — 1–8 of 20"
    s = load_state(d / "state.json")
    assert s.current_book_id == 42
    assert s.current_book_started_on == today
    assert s.bootstrap_consumed is True
    assert s.position == 8
    assert s.last_send_date == today
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_daily.py::test_bootstrap_path_snapshots_book_and_sends_first_highlights -v`
Expected: failure.

- [ ] **Step 3: Implement branch (a) in `src/readwise_review/daily.py`**

Insert this block in `run()` between the same-day idempotency check and branch (b):

```python
    # 5a. Bootstrap: if no current book and config has a bootstrap_book_id and we
    # haven't consumed it yet, snapshot that book and fall through to (d).
    if (
        state.current_book_id is None
        and config.bootstrap_book_id is not None
        and not state.bootstrap_consumed
    ):
        from datetime import timezone
        from readwise_review.state import HighlightSnapshot, save_snapshot, snapshot_path

        highlights = sorted(
            client.get_highlights(book_id=config.bootstrap_book_id),
            key=lambda h: (h.location if h.location is not None else 10**9, h.id),
        )
        snap = HighlightSnapshot(
            book_id=config.bootstrap_book_id,
            snapshotted_at=datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            highlights=highlights,
        )
        save_snapshot(snap, snapshot_path(data_dir, config.bootstrap_book_id))
        state = replace(
            state,
            current_book_id=config.bootstrap_book_id,
            current_book_started_on=today,
            position=0,
            bootstrap_consumed=True,
        )
        # Fall through to branch (d). The single save_state at the end of (d)
        # persists the bootstrap mutation.
```

If a workflow run fails after the snapshot is written but before `save_state`, the next run sees state still has `current_book_id == None` and `bootstrap_consumed == False`, so it re-snapshots — harmless overhead, not a correctness bug.

- [ ] **Step 4: Run all daily tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_daily.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/readwise_review/daily.py tests/unit/test_daily.py
git commit -m "feat: daily bootstrap branch falls through to highlights"
```

---

### Task 14: Select entrypoint

**Files:**
- Create: `src/readwise_review/select.py`
- Create: `tests/unit/test_select.py`

The select entrypoint is triggered by the `select-book` workflow on `issues.opened`. It parses the issue title, validates, snapshots the chosen book, updates state, comments + closes the issue.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_select.py`:

```python
"""Select entrypoint: parses issue, snapshots book, updates state, comments + closes issue."""

import json
from dataclasses import replace as dc_replace
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from readwise_review.select import (
    InvalidIssueError,
    parse_book_id,
    run as run_select,
)
from readwise_review.state import (
    BookEntry,
    BooksFile,
    Highlight,
    HighlightSnapshot,
    State,
    load_state,
    save_books,
    save_snapshot,
    save_state,
)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    save_state(State(
        current_book_id=None,
        current_book_started_on=None,
        position=0,
        last_send_date=None,
        picker_email_sent_on=None,
        bootstrap_consumed=False,
        history=[],
    ), d / "state.json")
    save_books(BooksFile(
        fetched_at="2026-05-01T12:00:00Z",
        books=[
            BookEntry(id=42, title="My Book", author="Author", num_highlights=10),
            BookEntry(id=99, title="Other", author="Other Author", num_highlights=20),
        ],
    ), d / "books.json")
    (d / "highlights").mkdir()
    return d


# ---- title parsing -------------------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("select-book: 42", 42),
    ("select-book:42", 42),
    ("select-book:  12345", 12345),
])
def test_parse_book_id_valid(title: str, expected: int) -> None:
    assert parse_book_id(title) == expected


@pytest.mark.parametrize("title", [
    "select-book:",
    "select-book: abc",
    "selectbook: 42",
    "random title",
])
def test_parse_book_id_invalid_raises(title: str) -> None:
    with pytest.raises(InvalidIssueError):
        parse_book_id(title)


# ---- happy path ----------------------------------------------------------

def test_select_book_happy_path(data_dir: Path) -> None:
    today = date(2026, 5, 6)
    client = MagicMock()
    client.get_highlights.return_value = iter([
        Highlight(id=1, text="A", location=2, location_type="page", note="", highlighted_at=None),
        Highlight(id=2, text="B", location=1, location_type="page", note="", highlighted_at=None),
    ])
    client.list_books.return_value = iter([
        BookEntry(id=42, title="My Book", author="Author", num_highlights=2),
        BookEntry(id=99, title="Other", author="Other Author", num_highlights=20),
    ])
    comments: list[str] = []
    closed: list[bool] = []

    run_select(
        issue_title="select-book: 42",
        issue_user="ericsallinger",
        issue_number=7,
        repo_owner="ericsallinger",
        client=client,
        data_dir=data_dir,
        commit_fn=lambda *a, **k: True,
        comment_fn=lambda body: comments.append(body),
        close_fn=lambda: closed.append(True),
        now_chicago_date=today,
    )

    s = load_state(data_dir / "state.json")
    assert s.current_book_id == 42
    assert s.current_book_started_on == today
    assert s.position == 0
    assert s.picker_email_sent_on is None
    snap_path = data_dir / "highlights" / "42.json"
    raw = json.loads(snap_path.read_text())
    assert [h["id"] for h in raw["highlights"]] == [2, 1]
    assert closed == [True]
    assert comments and "Selected" in comments[0]


# ---- skip non-owner / wrong-prefix issues -------------------------------

def test_select_skips_when_not_owner(data_dir: Path) -> None:
    client = MagicMock()
    closed: list[bool] = []
    run_select(
        issue_title="select-book: 42",
        issue_user="some-other-user",
        issue_number=7,
        repo_owner="ericsallinger",
        client=client,
        data_dir=data_dir,
        commit_fn=lambda *a, **k: True,
        comment_fn=lambda b: None,
        close_fn=lambda: closed.append(True),
        now_chicago_date=date(2026, 5, 6),
    )
    assert closed == []
    client.get_highlights.assert_not_called()


def test_select_skips_when_title_lacks_prefix(data_dir: Path) -> None:
    client = MagicMock()
    closed: list[bool] = []
    run_select(
        issue_title="please review this PR",
        issue_user="ericsallinger",
        issue_number=7,
        repo_owner="ericsallinger",
        client=client,
        data_dir=data_dir,
        commit_fn=lambda *a, **k: True,
        comment_fn=lambda b: None,
        close_fn=lambda: closed.append(True),
        now_chicago_date=date(2026, 5, 6),
    )
    assert closed == []
    client.get_highlights.assert_not_called()


# ---- already-on-this-book idempotency -----------------------------------

def test_select_no_op_when_already_on_this_book(data_dir: Path) -> None:
    state = load_state(data_dir / "state.json")
    save_state(
        dc_replace(state, current_book_id=42, current_book_started_on=date(2026, 5, 1)),
        data_dir / "state.json",
    )
    client = MagicMock()
    comments: list[str] = []
    closed: list[bool] = []
    run_select(
        issue_title="select-book: 42",
        issue_user="ericsallinger",
        issue_number=7,
        repo_owner="ericsallinger",
        client=client,
        data_dir=data_dir,
        commit_fn=lambda *a, **k: True,
        comment_fn=lambda b: comments.append(b),
        close_fn=lambda: closed.append(True),
        now_chicago_date=date(2026, 5, 6),
    )
    client.get_highlights.assert_not_called()
    assert comments and "Already on this book" in comments[0]
    assert closed == [True]


# ---- abandonment of mid-cycle book --------------------------------------

def test_select_abandons_current_book_to_history(data_dir: Path) -> None:
    state = load_state(data_dir / "state.json")
    save_state(
        dc_replace(
            state,
            current_book_id=99,
            current_book_started_on=date(2026, 4, 1),
            position=5,
        ),
        data_dir / "state.json",
    )
    save_snapshot(HighlightSnapshot(
        book_id=99,
        snapshotted_at="2026-04-01T12:00:00Z",
        highlights=[Highlight(id=i, text=str(i), location=i, location_type="page", note="", highlighted_at=None) for i in range(20)],
    ), data_dir / "highlights" / "99.json")

    client = MagicMock()
    client.get_highlights.return_value = iter([
        Highlight(id=1, text="A", location=1, location_type="page", note="", highlighted_at=None),
    ])
    client.list_books.return_value = iter([
        BookEntry(id=42, title="My Book", author="Author", num_highlights=1),
        BookEntry(id=99, title="Other", author="Other Author", num_highlights=20),
    ])

    run_select(
        issue_title="select-book: 42",
        issue_user="ericsallinger",
        issue_number=7,
        repo_owner="ericsallinger",
        client=client,
        data_dir=data_dir,
        commit_fn=lambda *a, **k: True,
        comment_fn=lambda b: None,
        close_fn=lambda: None,
        now_chicago_date=date(2026, 5, 6),
    )

    s = load_state(data_dir / "state.json")
    assert s.current_book_id == 42
    assert s.current_book_started_on == date(2026, 5, 6)
    assert s.position == 0
    assert len(s.history) == 1
    assert s.history[0].book_id == 99
    assert s.history[0].outcome == "abandoned"
    assert s.history[0].abandoned_at == date(2026, 5, 6)
    assert s.history[0].position_at_abandon == 5
    assert s.history[0].highlight_count == 20


# ---- malformed title ----------------------------------------------------

def test_select_malformed_title_comments_and_closes(data_dir: Path) -> None:
    client = MagicMock()
    comments: list[str] = []
    closed: list[bool] = []
    run_select(
        issue_title="select-book: not-a-number",
        issue_user="ericsallinger",
        issue_number=7,
        repo_owner="ericsallinger",
        client=client,
        data_dir=data_dir,
        commit_fn=lambda *a, **k: True,
        comment_fn=lambda b: comments.append(b),
        close_fn=lambda: closed.append(True),
        now_chicago_date=date(2026, 5, 6),
    )
    client.get_highlights.assert_not_called()
    assert comments and "Could not parse" in comments[0]
    assert closed == [True]


# ---- unknown book id ---------------------------------------------------

def test_select_unknown_book_id_after_refresh_comments_and_closes(data_dir: Path) -> None:
    client = MagicMock()
    client.list_books.return_value = iter([
        BookEntry(id=42, title="My Book", author="Author", num_highlights=10),
        BookEntry(id=99, title="Other", author="Other Author", num_highlights=20),
    ])
    comments: list[str] = []
    closed: list[bool] = []
    run_select(
        issue_title="select-book: 999",
        issue_user="ericsallinger",
        issue_number=7,
        repo_owner="ericsallinger",
        client=client,
        data_dir=data_dir,
        commit_fn=lambda *a, **k: True,
        comment_fn=lambda b: comments.append(b),
        close_fn=lambda: closed.append(True),
        now_chicago_date=date(2026, 5, 6),
    )
    client.get_highlights.assert_not_called()
    assert comments and "not found" in comments[0]
    assert closed == [True]


# ---- empty highlights --------------------------------------------------

def test_select_book_with_zero_highlights_comments_and_closes(data_dir: Path) -> None:
    client = MagicMock()
    client.get_highlights.return_value = iter([])
    client.list_books.return_value = iter([
        BookEntry(id=42, title="My Book", author="Author", num_highlights=0),
    ])
    comments: list[str] = []
    closed: list[bool] = []
    run_select(
        issue_title="select-book: 42",
        issue_user="ericsallinger",
        issue_number=7,
        repo_owner="ericsallinger",
        client=client,
        data_dir=data_dir,
        commit_fn=lambda *a, **k: True,
        comment_fn=lambda b: comments.append(b),
        close_fn=lambda: closed.append(True),
        now_chicago_date=date(2026, 5, 6),
    )
    assert comments and "no highlights" in comments[0]
    assert closed == [True]
    s = load_state(data_dir / "state.json")
    assert s.current_book_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_select.py -v`
Expected: ImportError on `select.run` / `parse_book_id`.

- [ ] **Step 3: Write `src/readwise_review/select.py`**

```python
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

    new_state = replace(
        state,
        current_book_id=book_id,
        current_book_started_on=now_chicago_date,
        position=0,
        picker_email_sent_on=None,
        history=new_history,
    )
    save_state(new_state, data_dir / "state.json")

    refresh_books_run(client=client, data_dir=data_dir, commit_fn=commit_fn)

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_select.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add src/readwise_review/select.py tests/unit/test_select.py
git commit -m "feat: select entrypoint with parsing, snapshotting, abandonment, idempotency"
```

---

### Task 15: CI workflow (tests.yml)

**Files:**
- Create: `.github/workflows/tests.yml`

- [ ] **Step 1: Write `.github/workflows/tests.yml`**

```yaml
name: Tests

on:
  push:
  pull_request:

jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - run: pip install -e ".[dev]"
      - run: pytest -v
```

- [ ] **Step 2: Push and verify CI passes**

```bash
git add .github/workflows/tests.yml
git commit -m "ci: tests workflow runs unit suite on push and PR"
git push
```

Open `https://github.com/ericsallinger/readwise-review/actions` and confirm the run succeeds.

---

### Task 16: refresh-books.yml workflow

**Files:**
- Create: `.github/workflows/refresh-books.yml`

- [ ] **Step 1: Write `.github/workflows/refresh-books.yml`**

```yaml
name: Refresh books

on:
  schedule:
    - cron: '0 12 * * 0'   # Sunday 12:00 UTC
  workflow_dispatch:

concurrency:
  group: refresh-books
  cancel-in-progress: false

permissions:
  contents: write

jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - run: pip install -e .
      - run: python -m readwise_review.refresh
        env:
          READWISE_TOKEN: ${{ secrets.READWISE_TOKEN }}
```

- [ ] **Step 2: Commit and push**

```bash
git add .github/workflows/refresh-books.yml
git commit -m "ci: refresh-books workflow (Sunday cron + workflow_dispatch)"
git push
```

- [ ] **Step 3: Smoke-test manually**

You will need `READWISE_TOKEN` in repo secrets first (Settings → Secrets and variables → Actions). Then go to Actions → Refresh books → "Run workflow." Verify a commit lands on `data/books.json` with the user's library.

---

### Task 17: daily-email.yml workflow

**Files:**
- Create: `.github/workflows/daily-email.yml`

- [ ] **Step 1: Write `.github/workflows/daily-email.yml`**

```yaml
name: Daily email

on:
  schedule:
    - cron: '0 12 * * 1-5'   # 7am CDT / 6am CST
    - cron: '0 13 * * 1-5'   # 8am CDT / 7am CST
  workflow_dispatch:

concurrency:
  group: daily-email
  cancel-in-progress: false

permissions:
  contents: write

jobs:
  send:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - run: pip install -e .
      - run: python -m readwise_review.daily
        env:
          READWISE_TOKEN: ${{ secrets.READWISE_TOKEN }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          GITHUB_REPOSITORY: ${{ github.repository }}
```

- [ ] **Step 2: Commit and push**

```bash
git add .github/workflows/daily-email.yml
git commit -m "ci: daily-email workflow (twice-daily cron + workflow_dispatch)"
git push
```

- [ ] **Step 3: Manual smoke test**

Add `GMAIL_APP_PASSWORD` to repo secrets. Edit `config.yaml` to set `bootstrap_book_id` to a real book id from `data/books.json`. Commit and push. The next 7am Chicago weekday delivers the first email.

To bypass the hour gate for an immediate end-to-end check, run locally:

```bash
READWISE_TOKEN=... GMAIL_APP_PASSWORD=... GITHUB_REPOSITORY=ericsallinger/readwise-review \
  .venv/bin/python -c "
from datetime import datetime; from zoneinfo import ZoneInfo
from readwise_review.daily import run; from readwise_review.config import load_config
from readwise_review.readwise import ReadwiseClient
from readwise_review.email_send import send_email
from readwise_review.git_io import commit_and_push
from pathlib import Path
import os
cfg = load_config('config.yaml')
client = ReadwiseClient(os.environ['READWISE_TOKEN'])
run(config=cfg, data_dir=Path('data'), client=client, send_email_fn=send_email,
    commit_fn=commit_and_push, gmail_app_password=os.environ['GMAIL_APP_PASSWORD'],
    repo=os.environ['GITHUB_REPOSITORY'],
    now=datetime(2026,5,6,7,0,tzinfo=ZoneInfo('America/Chicago')))
"
```

---

### Task 18: select-book.yml workflow

**Files:**
- Create: `.github/workflows/select-book.yml`

- [ ] **Step 1: Write `.github/workflows/select-book.yml`**

```yaml
name: Select book

on:
  issues:
    types: [opened]

concurrency:
  group: select-book
  cancel-in-progress: false

permissions:
  contents: write
  issues: write

jobs:
  select:
    if: |
      github.event.issue.user.login == github.repository_owner &&
      startsWith(github.event.issue.title, 'select-book:')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - run: pip install -e .
      - run: python -m readwise_review.select
        env:
          READWISE_TOKEN: ${{ secrets.READWISE_TOKEN }}
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPOSITORY: ${{ github.repository }}
          GITHUB_EVENT_PATH: ${{ github.event_path }}
```

The `gh` CLI inside `_make_gh_helpers` reads `GH_TOKEN`; the `permissions: issues: write` plus the default `secrets.GITHUB_TOKEN` cover this.

- [ ] **Step 2: Commit and push**

```bash
git add .github/workflows/select-book.yml
git commit -m "ci: select-book workflow (issues:opened with author/title filter)"
git push
```

- [ ] **Step 3: Smoke test**

Open a new issue manually with title `select-book: <real book id from data/books.json>`. The workflow should fire, comment confirmation, close the issue, and update `data/state.json` with the selected book.

---

### Task 19: README and final setup checklist

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
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
```

- [ ] **Step 2: Commit and push**

```bash
git add README.md
git commit -m "docs: README with setup checklist and daily flow overview"
git push
```

---

## Spec coverage check

| Spec section | Implemented in |
|---|---|
| Architecture: 3 workflows + Python module | Tasks 15, 16, 17, 18 + Tasks 9–14 |
| Concurrency groups | Tasks 16, 17, 18 |
| Timezone handling (`zoneinfo`, hour gate, UTC `*_at`) | Task 10, Tasks 9/13/14 |
| Repo layout | Task 1 + per-module tasks |
| Readwise endpoints (`/auth/`, `/books/`, `/highlights/`) | Tasks 5, 6 |
| Pagination via `next` URL | Task 5 |
| Rate-limit retry (429 / 5xx) | Task 5 |
| `config.yaml` schema | Tasks 1, 2 |
| `state.json` schema | Tasks 1, 3 |
| `books.json` schema | Tasks 1, 3 |
| `highlights/<id>.json` snapshot schema | Task 3 |
| Daily logic — hour gate | Task 10 |
| Daily logic — same-day idempotency | Task 10 |
| Daily logic — bootstrap branch (a) | Task 13 |
| Daily logic — silence branch (b) | Task 11 |
| Daily logic — picker branch (c) | Task 11 |
| Daily logic — highlights / finishing branch (d) | Task 12 |
| Selection logic — author filter | Task 14 |
| Selection logic — title prefix filter | Task 14 |
| Selection logic — book_id parse | Task 14 |
| Selection logic — already-on-book idempotency | Task 14 |
| Selection logic — book validation + refresh on miss | Task 14 |
| Selection logic — empty-highlights rejection | Task 14 |
| Selection logic — abandonment of mid-cycle book | Task 14 |
| Selection logic — comment + close | Task 14 |
| Refresh logic | Task 9 |
| Email rendering — highlights template | Task 7 |
| Email rendering — finishing variant with picker | Task 7 |
| Email rendering — picker-only template | Task 7 |
| No-emoji invariant | Task 7 (test enforces) |
| Email sending — Gmail SMTP | Task 8 |
| Idempotency invariants | Tasks 10–14 |
| DST handling | Tasks 10 + 17 |
| SMTP-failure resume | Task 12 |
| Issue-spam filter (workflow + script-level) | Tasks 14, 18 |
| Tests strategy (unit + integration markers) | Task 1, Task 15 |
| Token validation fail-fast | Tasks 5, 6 + entrypoints in Tasks 9, 10, 14 |
| Setup checklist | Task 19 |

**Spec gap noted:** the spec mentions `daily.py --dry-run` as a local dev affordance. This plan omits it because the inline-script smoke-test demonstrated in Task 17 (calling `daily.run()` with an arbitrary `now`) covers the same need with no production code change. If a real `--dry-run` flag is desired, add a Task 12.5 that adds `dry_run: bool = False` to `daily.run()`, wraps `send_email_fn` with a stdout-printer when true, and exposes the flag via `argparse` in `main()`.
