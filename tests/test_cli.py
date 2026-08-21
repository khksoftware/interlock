# SPDX-License-Identifier: Apache-2.0
"""End-to-end tests for the unified `interlock` command (`interlock.cli`) -- install, arm,
disarm, and status, across both `git.*` and `turn.*` identifiers, driven exactly as an
adopter would run it: `python -m interlock ...` as a real subprocess.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", "-m", "interlock", *args],
        cwd=str(cwd), capture_output=True, text=True, check=False,
    )


class TestStatus:
    def test_status_with_no_id_lists_every_known_id(self, sandbox: Path) -> None:
        result = run_cli(sandbox, "status")
        assert result.returncode == 0, result.stderr
        assert "git.protected-paths" in result.stdout
        assert "turn.idle-roster" in result.stdout

    def test_a_fresh_sandbox_reports_not_installed_and_not_armed(self, sandbox: Path) -> None:
        result = run_cli(sandbox, "status", "git.protected-paths")
        assert "not installed" in result.stdout
        assert "not armed" in result.stdout

    def test_unknown_id_is_reported_and_exits_nonzero(self, sandbox: Path) -> None:
        result = run_cli(sandbox, "status", "bogus.nothing")
        assert result.returncode != 0
        assert "unknown id" in result.stderr


class TestGitInstallAndArm:
    def test_install_writes_the_shim_and_arms(self, sandbox: Path) -> None:
        result = run_cli(sandbox, "install", "git.protected-paths")
        assert result.returncode == 0, result.stderr
        assert (sandbox / ".git" / "hooks" / "pre-commit").is_file()

        status = run_cli(sandbox, "status", "git.protected-paths")
        assert "installed" in status.stdout
        assert "armed" in status.stdout
        assert "not armed" not in status.stdout

    def test_arm_alone_does_not_write_the_shim(self, sandbox: Path) -> None:
        result = run_cli(sandbox, "arm", "git.protected-paths")
        assert result.returncode == 0, result.stderr
        assert not (sandbox / ".git" / "hooks" / "pre-commit").is_file()

        status = run_cli(sandbox, "status", "git.protected-paths")
        assert "not installed" in status.stdout
        assert "not armed" not in status.stdout  # armed, just not installed

    def test_disarm_removes_only_the_marker(self, sandbox: Path) -> None:
        run_cli(sandbox, "install", "git.protected-paths")
        result = run_cli(sandbox, "disarm", "git.protected-paths")
        assert result.returncode == 0, result.stderr
        # The shim stays -- disarm never touches shared wiring, only this worktree's marker.
        assert (sandbox / ".git" / "hooks" / "pre-commit").is_file()
        status = run_cli(sandbox, "status", "git.protected-paths")
        assert "not armed" in status.stdout


class TestTurnInstallAndArm:
    def test_arm_writes_a_marker_under_the_same_git_dir_as_a_git_gate(self, sandbox: Path) -> None:
        run_cli(sandbox, "arm", "turn.idle-roster")
        run_cli(sandbox, "arm", "git.protected-paths")
        markers = {p.name for p in (sandbox / ".git").iterdir() if p.is_file()}
        assert any("turn-idle-roster" in name for name in markers)
        assert any("git-protected-paths" in name for name in markers)

    def test_install_prints_an_advisory_wiring_note_and_never_writes_settings_json(
        self, sandbox: Path,
    ) -> None:
        result = run_cli(sandbox, "install", "turn.idle-roster")
        assert result.returncode == 0, result.stderr
        assert "settings.json" in result.stdout
        assert not (sandbox / ".claude").exists()
        assert not (sandbox / "settings.json").exists()

    def test_disarm_a_turn_hook(self, sandbox: Path) -> None:
        run_cli(sandbox, "arm", "turn.idle-roster")
        result = run_cli(sandbox, "disarm", "turn.idle-roster")
        assert result.returncode == 0, result.stderr
        status = run_cli(sandbox, "status", "turn.idle-roster")
        assert "not armed" in status.stdout


class TestUnknownIdEveryVerb:
    def test_install_unknown_id(self, sandbox: Path) -> None:
        result = run_cli(sandbox, "install", "bogus.nothing")
        assert result.returncode != 0
        assert "unknown id" in result.stderr

    def test_arm_unknown_id(self, sandbox: Path) -> None:
        result = run_cli(sandbox, "arm", "bogus.nothing")
        assert result.returncode != 0
        assert "unknown id" in result.stderr

    def test_disarm_unknown_id(self, sandbox: Path) -> None:
        result = run_cli(sandbox, "disarm", "bogus.nothing")
        assert result.returncode != 0
        assert "unknown id" in result.stderr
