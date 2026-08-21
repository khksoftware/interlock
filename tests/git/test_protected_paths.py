# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

from interlock.git.hookkit import arm_marker, install, is_armed
from interlock.git.protected_paths import SPEC, protected_path_failures
from tests.conftest import run_git


class TestThePredicate:
    def test_no_protected_paths_configured_means_nothing_is_refused(self, sandbox: Path) -> None:
        (sandbox / "secrets" / "key.pem").parent.mkdir()
        (sandbox / "secrets" / "key.pem").write_text("shh\n", encoding="utf-8")
        run_git(sandbox, "add", "secrets/key.pem")
        assert protected_path_failures(sandbox) == ()

    def test_an_exact_protected_path_is_refused(self, sandbox: Path) -> None:
        (sandbox / "vendor.lock").write_text("v1\n", encoding="utf-8")
        run_git(sandbox, "add", "vendor.lock")
        failures = protected_path_failures(sandbox, protected_paths=("vendor.lock",))
        assert len(failures) == 1
        assert "vendor.lock" in failures[0]

    def test_a_protected_prefix_catches_everything_under_it(self, sandbox: Path) -> None:
        (sandbox / "legal").mkdir()
        (sandbox / "legal" / "contract.md").write_text("c\n", encoding="utf-8")
        run_git(sandbox, "add", "legal/contract.md")
        failures = protected_path_failures(sandbox, protected_prefixes=("legal/",))
        assert len(failures) == 1
        assert "legal/contract.md" in failures[0]

    def test_deleting_a_protected_path_is_refused_identically_to_editing_it(self, sandbox: Path) -> None:
        (sandbox / "vendor.lock").write_text("v1\n", encoding="utf-8")
        run_git(sandbox, "add", "vendor.lock")
        run_git(sandbox, "commit", "-q", "-m", "add vendor.lock")
        run_git(sandbox, "rm", "-q", "vendor.lock")
        failures = protected_path_failures(sandbox, protected_paths=("vendor.lock",))
        assert len(failures) == 1

    def test_an_unrelated_commit_is_untouched(self, sandbox: Path) -> None:
        (sandbox / "ordinary.txt").write_text("fine\n", encoding="utf-8")
        run_git(sandbox, "add", "ordinary.txt")
        assert protected_path_failures(sandbox, protected_paths=("vendor.lock",)) == ()


class TestTheInstaller:
    def test_install_writes_the_shim_and_arms_this_worktree(self, sandbox: Path, interpreter: Path) -> None:
        assert not is_armed(sandbox, SPEC)
        install(sandbox, SPEC, interpreter=interpreter)
        assert is_armed(sandbox, SPEC)
        hook = sandbox / ".git" / "hooks" / "pre-commit"
        assert hook.read_bytes().decode("utf-8") == SPEC.shim

    def test_install_is_idempotent(self, sandbox: Path, interpreter: Path) -> None:
        install(sandbox, SPEC, interpreter=interpreter)
        actions = install(sandbox, SPEC, interpreter=interpreter)
        assert any("already" in action for action in actions)

    def test_install_refuses_to_overwrite_a_foreign_hook(self, sandbox: Path, interpreter: Path) -> None:
        hooks = sandbox / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_text("#!/bin/sh\necho someone else's hook\n", encoding="utf-8")
        import pytest
        from interlock.errors import GateError

        with pytest.raises(GateError):
            install(sandbox, SPEC, interpreter=interpreter)

    def test_arm_marker_does_not_touch_the_hook_file(self, sandbox: Path, interpreter: Path) -> None:
        hooks = sandbox / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        composed = hooks / "pre-commit"
        composed.write_text("#!/bin/sh\n# composed by someone else\n", encoding="utf-8")
        arm_marker(sandbox, SPEC, interpreter=interpreter)
        assert is_armed(sandbox, SPEC)
        assert composed.read_text(encoding="utf-8") == "#!/bin/sh\n# composed by someone else\n"


class TestTheBlockActuallyBlocks:
    """Real `git commit` against a really-installed hook -- never a simulation."""

    def _configure(self, sandbox: Path) -> None:
        config = sandbox / "interlock.json"
        config.write_text('{"protected_paths": {"paths": ["vendor.lock"]}}', encoding="utf-8")
        run_git(sandbox, "add", "interlock.json")
        run_git(sandbox, "commit", "-q", "-m", "configure protected paths")

    def test_an_armed_worktree_refuses_a_real_commit_touching_a_protected_path(
        self, sandbox: Path, interpreter: Path,
    ) -> None:
        self._configure(sandbox)
        install(sandbox, SPEC, interpreter=interpreter)
        (sandbox / "vendor.lock").write_text("v1\n", encoding="utf-8")
        run_git(sandbox, "add", "vendor.lock")
        result = run_git(sandbox, "commit", "-q", "-m", "sneak in a vendor.lock change")
        assert result.returncode != 0
        assert run_git(sandbox, "log", "-1", "--format=%s").stdout.decode().strip() == "configure protected paths"

    def test_an_unarmed_worktree_passes_the_identical_fixture(self, sandbox: Path, interpreter: Path) -> None:
        self._configure(sandbox)
        # Note: never called. Proves the gate's silence is due to being unarmed, not to a
        # broken predicate.
        (sandbox / "vendor.lock").write_text("v1\n", encoding="utf-8")
        run_git(sandbox, "add", "vendor.lock")
        result = run_git(sandbox, "commit", "-q", "-m", "unarmed, so this lands")
        assert result.returncode == 0

    def test_no_verify_bypasses_the_armed_gate(self, sandbox: Path, interpreter: Path) -> None:
        self._configure(sandbox)
        install(sandbox, SPEC, interpreter=interpreter)
        (sandbox / "vendor.lock").write_text("v1\n", encoding="utf-8")
        run_git(sandbox, "add", "vendor.lock")
        result = run_git(sandbox, "commit", "-q", "--no-verify", "-m", "disclosed bypass")
        assert result.returncode == 0

    def test_an_ordinary_commit_untouched_by_the_gate_passes_while_armed(
        self, sandbox: Path, interpreter: Path,
    ) -> None:
        self._configure(sandbox)
        install(sandbox, SPEC, interpreter=interpreter)
        (sandbox / "ordinary.txt").write_text("fine\n", encoding="utf-8")
        run_git(sandbox, "add", "ordinary.txt")
        result = run_git(sandbox, "commit", "-q", "-m", "ordinary change")
        assert result.returncode == 0
