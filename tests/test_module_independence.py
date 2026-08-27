# SPDX-License-Identifier: Apache-2.0
"""Proves independent adoption is real in the CODE, not only claimed in prose.

Each test below makes a PHYSICAL trimmed copy of `src/interlock` with one host's
subpackage directory deleted outright, then runs real subprocesses against that trimmed
copy's own `PYTHONPATH` -- not a mock, not a monkeypatched import, an actual missing
directory on disk. If `interlock.git` genuinely does not import `interlock.turn` (and
vice versa), every check in the surviving host keeps working, including a REAL `git
commit` refusal / a REAL hook subprocess run, with the other host's directory simply not
there to import.

`interlock.registry` and `interlock.cli` are the one place in this distribution that
legitimately imports both hosts (see `registry.py`'s own docstring) -- this suite proves
that module fails to import in a trimmed copy, cleanly, precisely because it is the one
place that needs both, and every gate or hook module a real adopter would actually use
does not share that requirement.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"


def _trimmed_copy(tmp_path: Path, *, remove: str) -> Path:
    """A standalone copy of `src/` with `interlock/<remove>/` deleted outright."""
    dest = tmp_path / f"trimmed-without-{remove}"
    shutil.copytree(SRC, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    removed_dir = dest / "interlock" / remove
    assert removed_dir.is_dir(), f"expected {removed_dir} to exist before removal"
    shutil.rmtree(removed_dir)
    assert not removed_dir.exists()
    return dest


def _run_python(trimmed_src: Path, code: str, *, cwd: Path | None = None, env_extra: dict | None = None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(trimmed_src)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True, text=True, env=env, check=False,
    )


class TestGitHostIndependentOfTurnHost:
    def test_turn_subpackage_is_genuinely_absent(self, tmp_path: Path) -> None:
        trimmed = _trimmed_copy(tmp_path, remove="turn")
        assert not (trimmed / "interlock" / "turn").exists()
        assert (trimmed / "interlock" / "git").is_dir()

    def test_every_git_gate_module_imports_with_turn_absent(self, tmp_path: Path) -> None:
        trimmed = _trimmed_copy(tmp_path, remove="turn")
        code = (
            "import interlock.git.hookkit, interlock.git.protected_paths, "
            "interlock.git.absolute_local_path, interlock.git.commit_message_pattern, "
            "interlock.git.stash_invocation, interlock.git.synthetic_git_identity; "
            "print('GIT_HOST_OK')"
        )
        result = _run_python(trimmed, code)
        assert result.returncode == 0, result.stderr
        assert "GIT_HOST_OK" in result.stdout

    def test_importing_turn_fails_because_it_is_physically_gone(self, tmp_path: Path) -> None:
        trimmed = _trimmed_copy(tmp_path, remove="turn")
        result = _run_python(trimmed, "import interlock.turn")
        assert result.returncode != 0
        assert "ModuleNotFoundError" in result.stderr or "ImportError" in result.stderr

    def test_registry_and_cli_fail_cleanly_because_they_need_both_hosts(self, tmp_path: Path) -> None:
        trimmed = _trimmed_copy(tmp_path, remove="turn")
        result = _run_python(trimmed, "import interlock.registry")
        assert result.returncode != 0
        result_cli = _run_python(trimmed, "import interlock.cli")
        assert result_cli.returncode != 0

    def test_a_real_install_and_a_real_commit_refusal_work_with_turn_absent(
        self, tmp_path: Path, sandbox: Path, interpreter: Path,
    ) -> None:
        """The end-to-end proof: install a git gate and drive a REAL git commit through
        it, using ONLY the trimmed copy's own PYTHONPATH -- `interlock.turn` is not on
        disk anywhere this process can reach."""
        trimmed = _trimmed_copy(tmp_path, remove="turn")
        env = {"PYTHONPATH": str(trimmed)}
        full_env = dict(os.environ)
        full_env.update(env)

        install = subprocess.run(
            [str(interpreter), "-B", "-m", "interlock.git.cli.check_synthetic_git_identity", "--install"],
            cwd=str(sandbox), capture_output=True, text=True, env=full_env, check=False,
        )
        assert install.returncode == 0, install.stderr

        subprocess.run(("git", "config", "--local", "user.email", "leftover@example.invalid"), cwd=str(sandbox))
        (sandbox / "file.txt").write_text("x\n", encoding="utf-8")
        subprocess.run(("git", "add", "file.txt"), cwd=str(sandbox))
        # The installed shim itself execs the recorded interpreter with a bare `-B -m
        # interlock.git.cli...`, inheriting THIS process's environment -- which is why
        # PYTHONPATH (not sys.path) is what has to carry the trimmed copy.
        commit = subprocess.run(
            ("git", "commit", "-q", "-m", "should be refused"),
            cwd=str(sandbox), capture_output=True, env=full_env, check=False,
        )
        assert commit.returncode != 0, "the synthetic-identity gate should have refused this commit"


class TestTurnHostIndependentOfGitHost:
    def test_git_subpackage_is_genuinely_absent(self, tmp_path: Path) -> None:
        trimmed = _trimmed_copy(tmp_path, remove="git")
        assert not (trimmed / "interlock" / "git").exists()
        assert (trimmed / "interlock" / "turn").is_dir()

    def test_every_turn_hook_module_imports_with_git_absent(self, tmp_path: Path) -> None:
        trimmed = _trimmed_copy(tmp_path, remove="git")
        code = (
            "import interlock.turn.config, interlock.turn.outstanding, "
            "interlock.turn.session_record, interlock.turn.arming, "
            "interlock.turn.role_label, interlock.turn.announced_action, "
            "interlock.turn.idle_roster, interlock.turn.roster_reconciliation, "
            "interlock.turn.subagent_start, interlock.turn.subagent_stop, "
            "interlock.turn.user_prompt_submit; "
            "print('TURN_HOST_OK')"
        )
        result = _run_python(trimmed, code)
        assert result.returncode == 0, result.stderr
        assert "TURN_HOST_OK" in result.stdout

    def test_importing_git_fails_because_it_is_physically_gone(self, tmp_path: Path) -> None:
        trimmed = _trimmed_copy(tmp_path, remove="git")
        result = _run_python(trimmed, "import interlock.git")
        assert result.returncode != 0
        assert "ModuleNotFoundError" in result.stderr or "ImportError" in result.stderr

    def test_registry_and_cli_fail_cleanly_because_they_need_both_hosts(self, tmp_path: Path) -> None:
        trimmed = _trimmed_copy(tmp_path, remove="git")
        result = _run_python(trimmed, "import interlock.registry")
        assert result.returncode != 0
        result_cli = _run_python(trimmed, "import interlock.cli")
        assert result_cli.returncode != 0

    def test_a_real_hook_arms_and_blocks_with_git_absent(self, tmp_path: Path, sandbox: Path) -> None:
        """The end-to-end proof: arm a turn hook and drive a REAL subprocess invocation
        of it -- unarmed first (silent no-op), then armed (a real block) -- using ONLY
        the trimmed copy's own PYTHONPATH. `interlock.git` is not on disk anywhere this
        process can reach."""
        trimmed = _trimmed_copy(tmp_path, remove="git")
        full_env = dict(os.environ)
        full_env["PYTHONPATH"] = str(trimmed)

        record = sandbox / ".interlock" / "session_record.json"
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(
            '{"roster": {"state": "none", "entries": []}, '
            '"queue": [{"id": "PROJ-1", "status": "queued", "sequenced": true}]}',
            encoding="utf-8",
        )

        unarmed = subprocess.run(
            [sys.executable, "-B", "-m", "interlock.turn.idle_roster"],
            cwd=str(sandbox), input='{"stop_hook_active": false}',
            capture_output=True, text=True, env=full_env, check=False,
        )
        assert unarmed.returncode == 0
        assert unarmed.stdout.strip() == "", "unarmed should be a silent no-op even with interlock.git absent"

        arm = subprocess.run(
            [sys.executable, "-B", "-c", "from interlock.turn import arming; print(arming.arm('idle_roster'))"],
            cwd=str(sandbox), capture_output=True, text=True, env=full_env, check=False,
        )
        assert arm.returncode == 0, arm.stderr

        armed = subprocess.run(
            [sys.executable, "-B", "-m", "interlock.turn.idle_roster"],
            cwd=str(sandbox), input='{"stop_hook_active": false}',
            capture_output=True, text=True, env=full_env, check=False,
        )
        assert armed.returncode == 0
        assert '"decision": "block"' in armed.stdout


class TestGuardHostIndependentOfGitAndTurn:
    def test_guard_subpackage_is_genuinely_absent_from_a_git_only_or_turn_only_copy(
        self, tmp_path: Path,
    ) -> None:
        trimmed = _trimmed_copy(tmp_path, remove="guard")
        assert not (trimmed / "interlock" / "guard").exists()
        assert (trimmed / "interlock" / "git").is_dir()
        assert (trimmed / "interlock" / "turn").is_dir()

    def test_every_guard_hook_module_imports_with_git_and_turn_absent(self, tmp_path: Path) -> None:
        without_git = _trimmed_copy(tmp_path, remove="git")
        shutil.rmtree(without_git / "interlock" / "turn")
        code = "import interlock.guard.arming, interlock.guard.config, interlock.guard.execution_guard; print('GUARD_HOST_OK')"
        result = _run_python(without_git, code)
        assert result.returncode == 0, result.stderr
        assert "GUARD_HOST_OK" in result.stdout

    def test_importing_guard_fails_because_it_is_physically_gone(self, tmp_path: Path) -> None:
        trimmed = _trimmed_copy(tmp_path, remove="guard")
        result = _run_python(trimmed, "import interlock.guard")
        assert result.returncode != 0
        assert "ModuleNotFoundError" in result.stderr or "ImportError" in result.stderr

    def test_registry_and_cli_fail_cleanly_because_they_need_every_host(self, tmp_path: Path) -> None:
        trimmed = _trimmed_copy(tmp_path, remove="guard")
        result = _run_python(trimmed, "import interlock.registry")
        assert result.returncode != 0
        result_cli = _run_python(trimmed, "import interlock.cli")
        assert result_cli.returncode != 0

    def test_a_real_hook_arms_and_blocks_with_git_and_turn_absent(self, tmp_path: Path, sandbox: Path) -> None:
        """The end-to-end proof: arm the guard hook and drive a REAL subprocess invocation
        of it -- unarmed first (silent no-op), then armed (a real block) -- using ONLY a
        copy with `interlock.git` and `interlock.turn` both physically removed."""
        trimmed = _trimmed_copy(tmp_path, remove="git")
        shutil.rmtree(trimmed / "interlock" / "turn")
        full_env = dict(os.environ)
        full_env["PYTHONPATH"] = str(trimmed)

        unarmed = subprocess.run(
            [sys.executable, "-B", "-m", "interlock.guard.execution_guard"],
            cwd=str(sandbox),
            input='{"tool_name": "Bash", "tool_input": {"command": "git worktree add ../new origin/main"}}',
            capture_output=True, text=True, env=full_env, check=False,
        )
        assert unarmed.returncode == 0
        assert unarmed.stdout.strip() == "", "unarmed should be a silent no-op even with git/turn absent"

        arm = subprocess.run(
            [
                sys.executable, "-B", "-c",
                "from interlock.guard import arming; print(arming.arm('execution_guard'))",
            ],
            cwd=str(sandbox), capture_output=True, text=True, env=full_env, check=False,
        )
        assert arm.returncode == 0, arm.stderr

        armed = subprocess.run(
            [sys.executable, "-B", "-m", "interlock.guard.execution_guard"],
            cwd=str(sandbox),
            input='{"tool_name": "Bash", "tool_input": {"command": "git worktree add ../new origin/main"}}',
            capture_output=True, text=True, env=full_env, check=False,
        )
        assert armed.returncode == 0
        # Compact separators, unlike interlock.turn's hooks -- matches
        # execution_guard.block_reason's own json.dumps(..., separators=(",", ":")).
        assert '"decision":"block"' in armed.stdout
