# SPDX-License-Identifier: Apache-2.0
"""Shared sandbox-repository fixtures for the whole suite, both hosts alike.

Every test in this distribution runs against a throwaway `git init` sandbox created
fresh per test, never against a real project checkout. This is the same discipline the
gates and hooks themselves are built to be trustworthy under: a test suite proving a
check works is not credible if the proof runs against a shared, live repository other
work might be touching.

`run_git` captures bytes and decodes as UTF-8 explicitly -- never `text=True` -- for the
same reason :mod:`interlock.plumbing` does: `text=True` decodes with the platform's
default codepage on Windows, which is a latent defect for any non-ASCII content even
though this suite's own fixtures are ASCII-only today. One `run_git` for the whole suite,
here, is itself a small instance of the consolidation this framework's own README argues
for: the package this distribution's turn-boundary tests were extracted from carried an
independent `text=True` copy of this exact helper.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def run_git(cwd: Path, *arguments: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ("git", *arguments), cwd=str(cwd), capture_output=True, input=input_bytes, check=False,
    )


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A fresh git repository, one initial commit, an ordinary (non-synthetic) identity."""
    root = tmp_path / "repo"
    root.mkdir()
    run_git(root, "init", "-q")
    run_git(root, "config", "user.name", "Sandbox Tester")
    run_git(root, "config", "user.email", "sandbox-tester@sandbox.test")
    run_git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("sandbox\n", encoding="utf-8")
    run_git(root, "add", "README.md")
    result = run_git(root, "commit", "-q", "-m", "initial commit")
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return root


@pytest.fixture
def interpreter() -> Path:
    return Path(sys.executable)


__all__ = ("interpreter", "run_git", "sandbox")
