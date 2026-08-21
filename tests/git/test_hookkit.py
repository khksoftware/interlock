# SPDX-License-Identifier: Apache-2.0
"""Tests for the shared installer/render_shim machinery, plus the two ways more than one
`pre-commit` gate can share that one hook name (git dispatches exactly one file per hook
name): `install` composing them automatically (see `hookkit.install`'s own docstring and
`REVIEW_2026-08-21.md` Findings 2 and 3), and the hand-composed alternative
`docs/INTEGRATION.md` Section 5 still documents."""
from __future__ import annotations

from pathlib import Path

import pytest

from interlock.errors import GateError
from interlock.git.hookkit import (
    COMPOSED_DISPATCHER_SHIM, GateSpec, arm_marker, install, installation_state, is_armed,
    render_shim,
)
from interlock.git.absolute_local_path import SPEC as ABSOLUTE_LOCAL_PATH_SPEC
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


class TestInstallComposesAutomatically:
    """`install` used to refuse a second gate onto an already-occupied hook name
    outright, unconditionally -- even when the thing occupying it was another of this
    package's OWN gates (`REVIEW_2026-08-21.md` Finding 2: the README's own quickstart
    hits this on its third line, every time, from a fresh repository). It now composes
    instead, but only ever onto content it recognizes as its own."""

    def test_a_second_gate_composes_rather_than_refuses(
        self, sandbox: Path, interpreter: Path,
    ) -> None:
        install(sandbox, PROTECTED_PATHS_SPEC, interpreter=interpreter)
        actions = install(sandbox, IDENTITY_SPEC, interpreter=interpreter)
        assert any("composed" in action for action in actions)
        hook = sandbox / ".git" / "hooks" / "pre-commit"
        assert hook.read_bytes().decode("utf-8") == COMPOSED_DISPATCHER_SHIM

    def test_a_third_gate_composes_onto_the_same_dispatcher(
        self, sandbox: Path, interpreter: Path,
    ) -> None:
        install(sandbox, PROTECTED_PATHS_SPEC, interpreter=interpreter)
        install(sandbox, IDENTITY_SPEC, interpreter=interpreter)
        install(sandbox, ABSOLUTE_LOCAL_PATH_SPEC, interpreter=interpreter)
        hook = sandbox / ".git" / "hooks" / "pre-commit"
        assert hook.read_bytes().decode("utf-8") == COMPOSED_DISPATCHER_SHIM
        components = sandbox / ".git" / "hooks" / "interlock-composed" / "pre-commit"
        assert (components / PROTECTED_PATHS_SPEC.marker_name).is_file()
        assert (components / IDENTITY_SPEC.marker_name).is_file()
        assert (components / ABSOLUTE_LOCAL_PATH_SPEC.marker_name).is_file()

    def test_reinstalling_an_already_composed_gate_is_idempotent(
        self, sandbox: Path, interpreter: Path,
    ) -> None:
        install(sandbox, PROTECTED_PATHS_SPEC, interpreter=interpreter)
        install(sandbox, IDENTITY_SPEC, interpreter=interpreter)
        before = (sandbox / ".git" / "hooks" / "pre-commit").read_bytes()
        actions = install(sandbox, IDENTITY_SPEC, interpreter=interpreter)
        after = (sandbox / ".git" / "hooks" / "pre-commit").read_bytes()
        assert before == after
        assert any("already composed" in action for action in actions)

    def test_a_genuinely_foreign_hook_is_still_refused_not_clobbered(
        self, sandbox: Path, interpreter: Path,
    ) -> None:
        hooks_dir = sandbox / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        foreign = hooks_dir / "pre-commit"
        foreign_content = "#!/bin/sh\necho 'an unrelated pre-existing project hook'\n"
        foreign.write_text(foreign_content, encoding="utf-8")
        with pytest.raises(GateError):
            install(sandbox, PROTECTED_PATHS_SPEC, interpreter=interpreter)
        # Untouched -- refusing must never silently rewrite content this package did not
        # recognize as its own.
        assert foreign.read_text(encoding="utf-8") == foreign_content

    def test_the_composed_gates_still_independently_refuse_real_bad_commits(
        self, sandbox: Path, interpreter: Path,
    ) -> None:
        install(sandbox, PROTECTED_PATHS_SPEC, interpreter=interpreter)
        install(sandbox, IDENTITY_SPEC, interpreter=interpreter)

        config = sandbox / "interlock.json"
        config.write_text('{"protected_paths": {"paths": ["vendor.lock"]}}', encoding="utf-8")
        run_git(sandbox, "add", "interlock.json")
        run_git(sandbox, "commit", "-q", "-m", "configure")

        (sandbox / "vendor.lock").write_text("v\n", encoding="utf-8")
        run_git(sandbox, "add", "vendor.lock")
        assert run_git(sandbox, "commit", "-q", "-m", "blocked by protected paths").returncode != 0
        run_git(sandbox, "reset", "-q", "vendor.lock")

        run_git(sandbox, "config", "--local", "user.email", "leftover@example.invalid")
        (sandbox / "ordinary.txt").write_text("x\n", encoding="utf-8")
        run_git(sandbox, "add", "ordinary.txt")
        assert run_git(sandbox, "commit", "-q", "-m", "blocked by identity gate").returncode != 0

        run_git(sandbox, "config", "--local", "user.email", "sandbox-tester@sandbox.test")
        assert run_git(sandbox, "commit", "-q", "-m", "passes both").returncode == 0

    def test_status_reports_composed_gates_as_installed_not_foreign(
        self, sandbox: Path, interpreter: Path,
    ) -> None:
        install(sandbox, PROTECTED_PATHS_SPEC, interpreter=interpreter)
        install(sandbox, IDENTITY_SPEC, interpreter=interpreter)
        for spec in (PROTECTED_PATHS_SPEC, IDENTITY_SPEC):
            installed, detail = installation_state(sandbox, spec)
            assert installed, detail
            assert "FOREIGN" not in detail


class TestComposingTwoPreCommitGatesOntoOneSharedHook:
    """git dispatches one `hooks/pre-commit` file; two gates that both use that hook name
    can still be composed BY HAND into one shim that runs both, exactly as
    `docs/INTEGRATION.md` Section 5 describes -- an alternative `install`'s own automatic
    composing (see `TestInstallComposesAutomatically` above) supersedes for the common
    case, but does not replace. This proves the hand-composed pattern still works end to
    end, on real installed hooks and a real `git commit`, and that `interlock status`
    recognizes it too rather than calling a correctly-enforcing hook FOREIGN."""

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

        # Finding 3: status must recognize this hand-composed, correctly-enforcing hook,
        # not call it FOREIGN just because it is not byte-identical to either gate's own
        # solo shim.
        for spec in (PROTECTED_PATHS_SPEC, IDENTITY_SPEC):
            installed, detail = installation_state(sandbox, spec)
            assert installed, detail
            assert "FOREIGN" not in detail


class TestGateSpecItself:
    def test_is_frozen(self) -> None:
        spec = GateSpec(
            marker_name="m", hook_name="pre-commit", shim="#!/bin/sh\n",
            cli_module="pkg.cli.mod", gate_label="test gate",
        )
        with pytest.raises(Exception):
            spec.marker_name = "other"  # type: ignore[misc]
