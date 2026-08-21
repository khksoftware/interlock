# SPDX-License-Identifier: Apache-2.0
"""Tests for the shared installer/render_shim machinery, plus the composition pattern
`docs/INTEGRATION.md` documents for running more than one `pre-commit` gate in one repository
(git dispatches exactly one file per hook name, so more than one gate sharing that hook name
must be composed into one physical shim)."""
from __future__ import annotations

from pathlib import Path

import pytest

from interlock.errors import GateError
from interlock.git.hookkit import GateSpec, arm_marker, install, is_armed, render_shim
from interlock.git.protected_paths import SPEC as PROTECTED_PATHS_SPEC
from interlock.git.synthetic_git_identity import SPEC as IDENTITY_SPEC
from tests.conftest import run_git


class TestRenderShim:
    def test_shim_embeds_no_machine_specific_path(self) -> None:
        shim = render_shim(
            marker_name="m", hook_name="pre-commit", cli_module="pkg.cli.mod", gate_label="test gate",
        )
        assert "C:\\" not in shim
        assert "/home/" not in shim
        assert "/Users/" not in shim

    def test_shim_is_a_pure_function_of_its_arguments(self) -> None:
        first = render_shim(marker_name="m", hook_name="pre-commit", cli_module="a.b", gate_label="g")
        second = render_shim(marker_name="m", hook_name="pre-commit", cli_module="a.b", gate_label="g")
        assert first == second

    def test_forwards_hook_arguments_appends_the_forwarding_form(self) -> None:
        without = render_shim(marker_name="m", hook_name="commit-msg", cli_module="a.b", gate_label="g")
        withit = render_shim(
            marker_name="m", hook_name="commit-msg", cli_module="a.b", gate_label="g",
            forwards_hook_arguments=True,
        )
        assert '"$@"' not in without
        assert '"$@"' in withit


class TestComposingTwoPreCommitGatesOntoOneSharedHook:
    """git dispatches one `hooks/pre-commit` file; two gates that both use that hook name
    must be composed by hand into one shim that runs both, exactly as
    `docs/INTEGRATION.md` describes. This proves the composition pattern actually works end
    to end, on real installed hooks and a real `git commit`."""

    def test_install_refuses_a_second_gate_once_the_first_owns_the_hook(
        self, sandbox: Path, interpreter: Path,
    ) -> None:
        install(sandbox, PROTECTED_PATHS_SPEC, interpreter=interpreter)
        with pytest.raises(GateError):
            install(sandbox, IDENTITY_SPEC, interpreter=interpreter)

    def test_hand_composed_shim_dispatches_to_both_gates_markers(
        self, sandbox: Path, interpreter: Path,
    ) -> None:
        # Compose a single pre-commit shim that checks both gates' own markers and execs both
        # CLIs in turn -- the pattern an adopter running more than one pre-commit gate follows.
        hooks_dir = sandbox / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        composed = hooks_dir / "pre-commit"
        composed.write_text(
            "#!/bin/sh\n"
            "set -e\n"
            'gate_dir="$(git rev-parse --git-dir)"\n'
            f'if [ -f "$gate_dir/{PROTECTED_PATHS_SPEC.marker_name}" ]; then\n'
            f'  "$(cat "$gate_dir/{PROTECTED_PATHS_SPEC.marker_name}")" -B -m '
            "interlock.git.cli.check_protected_paths || exit 1\n"
            "fi\n"
            f'if [ -f "$gate_dir/{IDENTITY_SPEC.marker_name}" ]; then\n'
            f'  "$(cat "$gate_dir/{IDENTITY_SPEC.marker_name}")" -B -m '
            "interlock.git.cli.check_synthetic_git_identity || exit 1\n"
            "fi\n",
            encoding="utf-8", newline="",
        )
        composed.chmod(0o755)
        arm_marker(sandbox, PROTECTED_PATHS_SPEC, interpreter=interpreter)
        arm_marker(sandbox, IDENTITY_SPEC, interpreter=interpreter)
        assert is_armed(sandbox, PROTECTED_PATHS_SPEC)
        assert is_armed(sandbox, IDENTITY_SPEC)

        config = sandbox / "interlock.json"
        config.write_text('{"protected_paths": {"paths": ["vendor.lock"]}}', encoding="utf-8")
        run_git(sandbox, "add", "interlock.json")
        run_git(sandbox, "commit", "-q", "-m", "configure")

        # The protected-paths gate fires.
        (sandbox / "vendor.lock").write_text("v\n", encoding="utf-8")
        run_git(sandbox, "add", "vendor.lock")
        assert run_git(sandbox, "commit", "-q", "-m", "blocked by protected paths").returncode != 0
        run_git(sandbox, "reset", "-q", "vendor.lock")

        # The synthetic-identity gate fires, independently, on an unrelated ordinary commit.
        run_git(sandbox, "config", "--local", "user.email", "leftover@example.invalid")
        (sandbox / "ordinary.txt").write_text("x\n", encoding="utf-8")
        run_git(sandbox, "add", "ordinary.txt")
        assert run_git(sandbox, "commit", "-q", "-m", "blocked by identity gate").returncode != 0

        # Restoring a real identity lets the composed shim pass both gates.
        run_git(sandbox, "config", "--local", "user.email", "sandbox-tester@sandbox.test")
        assert run_git(sandbox, "commit", "-q", "-m", "passes both").returncode == 0


class TestGateSpecItself:
    def test_is_frozen(self) -> None:
        spec = GateSpec(marker_name="m", hook_name="pre-commit", shim="#!/bin/sh\n")
        with pytest.raises(Exception):
            spec.marker_name = "other"  # type: ignore[misc]
