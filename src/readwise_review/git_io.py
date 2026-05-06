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
