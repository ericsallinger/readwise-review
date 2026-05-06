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
