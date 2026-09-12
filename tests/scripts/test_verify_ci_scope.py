"""Falsifiers for source-tree reuse across protected CI contexts."""
from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from tools.verify_ci_scope import verify_scope


def git(root: Path, *args: str, input_text: str | None = None) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, text=True, input=input_text
    ).strip()


def commit_tree(root: Path, tree: str, *parents: str, message: str) -> str:
    command = ["commit-tree", tree]
    for parent in parents:
        command.extend(["-p", parent])
    return git(root, *command, input_text=message + "\n")


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str | Path]:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "CI test")
    git(tmp_path, "config", "user.email", "ci@example.invalid")
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2026-01-01T00:00:00Z")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2026-01-01T00:00:00Z")

    tracked = tmp_path / "tracked.txt"
    tracked.write_text("base\n")
    git(tmp_path, "add", "tracked.txt")
    git(tmp_path, "commit", "-q", "-m", "base")
    base = git(tmp_path, "rev-parse", "HEAD")

    tracked.write_text("head\n")
    git(tmp_path, "commit", "-q", "-am", "head")
    head = git(tmp_path, "rev-parse", "HEAD")
    head_tree = git(tmp_path, "rev-parse", "HEAD^{tree}")
    equivalent_merge = commit_tree(
        tmp_path, head_tree, base, head, message="synthetic merge"
    )

    extra = tmp_path / "merge-only.txt"
    extra.write_text("unexpected\n")
    git(tmp_path, "add", "merge-only.txt")
    changed_tree = git(tmp_path, "write-tree")
    changed_merge = commit_tree(
        tmp_path, changed_tree, base, head, message="changed synthetic merge"
    )
    return {
        "root": tmp_path,
        "base": base,
        "head": head,
        "equivalent_merge": equivalent_merge,
        "changed_merge": changed_merge,
    }


def test_exact_head_requires_the_advertised_commit(repository: dict[str, str | Path]) -> None:
    root = repository["root"]
    head = repository["head"]
    assert isinstance(root, Path) and isinstance(head, str)
    git(root, "checkout", "-q", "--detach", head)
    result = verify_scope(
        root=root,
        scope="exact-head",
        expected_head=head,
        expected_event_sha=head,
    )
    assert result["full_execution_required"] is True
    assert result["tree_evidence_reused"] is False

    with pytest.raises(AssertionError, match="differs from advertised PR head"):
        verify_scope(
            root=root,
            scope="exact-head",
            expected_head=repository["base"],  # type: ignore[arg-type]
            expected_event_sha=head,
        )


def test_synthetic_merge_reuses_only_an_identical_head_tree(
    repository: dict[str, str | Path],
) -> None:
    root = repository["root"]
    base = repository["base"]
    head = repository["head"]
    equivalent = repository["equivalent_merge"]
    changed = repository["changed_merge"]
    assert all(isinstance(value, str) for value in (base, head, equivalent, changed))
    assert isinstance(root, Path)

    git(root, "checkout", "-q", "--detach", equivalent)  # type: ignore[arg-type]
    result = verify_scope(
        root=root,
        scope="synthetic-merge",
        expected_head=head,  # type: ignore[arg-type]
        expected_base=base,  # type: ignore[arg-type]
        expected_event_sha=equivalent,  # type: ignore[arg-type]
    )
    assert result["full_execution_required"] is False
    assert result["tree_evidence_reused"] is True

    git(root, "checkout", "-q", "--detach", changed)  # type: ignore[arg-type]
    with pytest.raises(AssertionError, match="changes the certified PR-head source tree"):
        verify_scope(
            root=root,
            scope="synthetic-merge",
            expected_head=head,  # type: ignore[arg-type]
            expected_base=base,  # type: ignore[arg-type]
            expected_event_sha=changed,  # type: ignore[arg-type]
        )


def test_synthetic_merge_requires_exact_parent_identity(
    repository: dict[str, str | Path],
) -> None:
    root = repository["root"]
    base = repository["base"]
    head = repository["head"]
    equivalent = repository["equivalent_merge"]
    assert isinstance(root, Path)
    assert all(isinstance(value, str) for value in (base, head, equivalent))
    git(root, "checkout", "-q", "--detach", equivalent)  # type: ignore[arg-type]

    with pytest.raises(AssertionError, match="first parent"):
        verify_scope(
            root=root,
            scope="synthetic-merge",
            expected_head=head,  # type: ignore[arg-type]
            expected_base=head,  # type: ignore[arg-type]
            expected_event_sha=equivalent,  # type: ignore[arg-type]
        )
