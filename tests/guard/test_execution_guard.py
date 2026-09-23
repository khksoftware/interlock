# SPDX-License-Identifier: Apache-2.0
"""Tests for :mod:`interlock.guard.execution_guard` -- the ``PreToolUse``-shaped guard
that refuses a high-confidence expensive command shape before it runs.

Red-green discipline: each rule this hook recognizes is proven to fire on a matching
shape and NOT fire on the closest safe neighbour, matching the convention every gate and
hook in this distribution already follows. A dedicated class proves the payload-stripping
repair -- content inside a heredoc/here-string body must never be scanned as if it were the
command itself, while the surrounding invocation shape still is.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from interlock.guard import arming, execution_guard as hook


def _hold_open(target: Path, seconds: float):
    """Open `target` for read from a second thread and release it after `seconds`. Module
    level -- rather than the `_held` staticmethod on `TestAtomicWriteSurvivesAConcurrent
    Reader` below -- so `ENG-00734`'s new claim-primitive tests can use it without reaching
    into another class."""
    import threading

    opened = threading.Event()

    def hold() -> None:
        with open(target, "rb"):
            opened.set()
            time.sleep(seconds)

    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    assert opened.wait(5.0), "the holding thread never opened the target"
    return thread


class TestCommandExtraction:
    def test_shell_shape(self) -> None:
        payload = {"tool_name": "Bash", "tool_input": {"command": "git worktree add x"}}
        assert hook.extract_command(payload) == "git worktree add x"

    def test_exec_source_shape(self) -> None:
        payload = {"tool_name": "functions.exec", "tool_input": {"source": "run(pytest tests)"}}
        assert "pytest" in hook.extract_command(payload)

    def test_powershell_and_command_prompt_shapes(self) -> None:
        for tool_name in ("PowerShell", "Cmd", "CommandPrompt", "Shell"):
            payload = {"tool_name": tool_name, "tool_input": {"command": "dir /s workspace"}}
            assert hook.extract_command(payload) == "dir /s workspace"

    def test_non_shell_tool_is_ignored(self) -> None:
        payload = {"tool_name": "Edit", "tool_input": {"command": "git worktree add x"}}
        assert hook.extract_command(payload) is None


class TestPayloadStripping:
    """A heredoc's or here-string's BODY is prose/data, not a command that will execute,
    and must not be scanned as if it were one."""

    def test_bash_heredoc_body_is_removed_but_the_invocation_shape_survives(self) -> None:
        command = "cat <<'EOF' > patch.json\nsome content\nEOF\n"
        stripped = hook.strip_payload_bodies(command)
        assert "cat <<'EOF' > patch.json" in stripped
        assert "some content" not in stripped

    def test_dash_heredoc_and_indented_terminator_are_recognized(self) -> None:
        command = "cat <<-EOF\n\tindented body\nEOF\n"
        stripped = hook.strip_payload_bodies(command)
        assert "indented body" not in stripped

    def test_powershell_herestring_body_is_removed(self) -> None:
        command = "$x = @'\nsome content\n'@\n"
        stripped = hook.strip_payload_bodies(command)
        assert "some content" not in stripped
        assert "$x = @'" in stripped

    def test_multiple_heredocs_in_one_command_are_each_stripped(self) -> None:
        command = "cat <<EOF1 > a\nfirst body\nEOF1\ncat <<EOF2 > b\nsecond body\nEOF2\n"
        stripped = hook.strip_payload_bodies(command)
        assert "first body" not in stripped
        assert "second body" not in stripped

    def test_ordinary_command_with_no_payload_marker_is_unchanged(self) -> None:
        command = "git status --short"
        assert hook.strip_payload_bodies(command) == command


class TestPayloadStrippingSafety:
    """Independent-review follow-up: an earlier version of this repair removed a
    false-positive class and created four false-negative classes. Each case here is one of
    the four positions actually driven against a real armed subprocess."""

    def test_a_heredoc_body_fed_to_bash_keeps_the_command_visible(self) -> None:
        command = "bash <<'EOF'\nfind . -name \"*.py\"\nEOF\n"
        stripped = hook.strip_payload_bodies(command)
        assert "find . -name" in stripped

    def test_a_heredoc_piped_into_bash_keeps_the_command_visible(self) -> None:
        command = "cat <<'EOF' | bash\npython -m pytest tests\nEOF\n"
        stripped = hook.strip_payload_bodies(command)
        assert "python -m pytest tests" in stripped

    def test_a_stray_double_angle_in_prose_does_not_discard_the_next_line(self) -> None:
        command = 'echo "shift the value << two places"\nfind . -name "*.py"\n'
        stripped = hook.strip_payload_bodies(command)
        assert "find . -name" in stripped

    def test_an_unterminated_heredoc_does_not_discard_the_rest_of_the_command(self) -> None:
        command = "cat <<'EOF'\npython -m pytest tests\n"
        stripped = hook.strip_payload_bodies(command)
        assert "python -m pytest tests" in stripped

    def test_a_heredoc_marker_inside_a_quoted_string_does_not_discard_the_line_between(self) -> None:
        """Re-review follow-up: ``<<`` is not a redirect operator inside a quoted string in
        any shell -- ``echo "a << ZZZ"`` followed by a real command and a later, entirely
        coincidental bare ``ZZZ`` line executes all three lines as ordinary prose plus two
        unrelated commands. A regex match on the two characters alone, without checking
        whether they sit outside quotes, read this as a genuine heredoc and stripped the
        real command sitting between the two coincidental lines."""
        command = 'echo "a << ZZZ"\nfind . -name "*.py"\nZZZ\n'
        stripped = hook.strip_payload_bodies(command)
        assert 'find . -name "*.py"' in stripped

    def test_an_apostrophe_before_a_genuine_heredoc_opener_leaves_its_body_visible(self) -> None:
        """What the fix above now tolerates, stated and tested explicitly: the quote-parity
        check cannot distinguish a genuine apostrophe in prose from an actual open quote, so
        an odd quote count ahead of a REAL heredoc opener on the same line reads as "not
        real" and its body is left un-stripped -- visible to the classifier rather than
        treated as inert data. Safe (a false positive at worst, never a silently dropped
        command) but a real, new behavioural cost of the fix, not a free one -- see
        ``TestClassification`` below for the concrete false positive this produces."""
        command = "echo don't care <<'EOF' > NOTE.md\nRun `python -m pytest tests -q` before reporting done.\nEOF\n"
        stripped = hook.strip_payload_bodies(command)
        assert "before reporting done" in stripped

    def test_a_heredoc_marker_inside_a_quoted_string_spanning_multiple_lines_does_not_discard_the_line_between(
        self,
    ) -> None:
        """A third independent review pass: the quote-parity check only looked at the ONE
        line a candidate ``<<`` sits on, resetting to "outside any quote" at the start of
        every line. A real double-quoted string is not obliged to close on the line it
        opened -- here it opens on the first line and does not close until the third -- so
        the ``<<`` on the second line was misread as a real heredoc opener, and the `find`
        line between it and the coincidental `ZZZ` terminator was silently dropped."""
        command = (
            'echo "first line of a quoted message\n'
            "and a value shifted << ZZZ\n"
            'find . -name "*.py"\n'
            "ZZZ\n"
        )
        stripped = hook.strip_payload_bodies(command)
        assert 'find . -name "*.py"' in stripped

    def test_a_backslash_escaped_quote_ahead_of_a_heredoc_marker_does_not_discard_the_line_between(
        self,
    ) -> None:
        """The same review pass: a backslash-escaped ``\\"`` was counted as a second real
        quote delimiter, making an ODD (still-open) quote count look EVEN (closed) by the
        time the parity check reached the ``<<`` -- when the whole line is actually one
        self-closing quoted string. The `find` line was silently dropped exactly as in the
        single-quote-count defect this closes alongside."""
        command = 'echo "she said \\" and a << ZZZ"\nfind . -name "*.py"\nZZZ\n'
        stripped = hook.strip_payload_bodies(command)
        assert 'find . -name "*.py"' in stripped


class TestClassification:
    @staticmethod
    def rule_ids(command: str) -> set[str]:
        return {item["rule_id"] for item in hook.classify_command(command)}

    def test_additional_worktree_blocks(self) -> None:
        assert "COST-WORKTREE-ADD" in self.rule_ids("git worktree add ../new origin/main")

    def test_broad_workspace_rg_blocks_but_exact_file_does_not(self) -> None:
        assert "COST-FULL-TREE-SCAN" in self.rule_ids("rg -n marker workspace --glob *.json")
        assert "COST-FULL-TREE-SCAN" not in self.rule_ids("rg -n marker workspace/system/state.json")

    def test_recursive_workspace_listing_blocks(self) -> None:
        assert "COST-FULL-TREE-SCAN" in self.rule_ids("Get-ChildItem -Path workspace -Recurse")

    def test_full_test_directory_blocks_but_exact_module_does_not(self) -> None:
        assert "COST-FULL-TEST-SUITE" in self.rule_ids("python -m pytest tests -q")
        assert "COST-FULL-TEST-SUITE" not in self.rule_ids("python -m pytest tests/test_one.py -q")

    def test_database_copy_blocks(self) -> None:
        assert "COST-DATABASE-COPY" in self.rule_ids("Copy-Item source.sqlite3 target.sqlite3")

    def test_recursive_hash_blocks(self) -> None:
        assert "COST-RECURSIVE-HASH" in self.rule_ids("Get-ChildItem workspace -Recurse | Get-FileHash")

    def test_heredoc_content_merely_mentioning_a_command_is_not_classified(self) -> None:
        command = (
            "cat <<'EOF' > NOTE.md\n"
            "Run `python -m pytest tests -q` before reporting done.\n"
            "EOF\n"
        )
        assert self.rule_ids(hook.strip_payload_bodies(command)) == set()

    def test_a_genuine_expensive_command_outside_a_heredoc_body_still_blocks(self) -> None:
        command = "python -m pytest tests -q <<'EOF'\nirrelevant input\nEOF\n"
        assert "COST-FULL-TEST-SUITE" in self.rule_ids(hook.strip_payload_bodies(command))

    def test_a_heredoc_body_fed_to_bash_is_still_classified(self) -> None:
        command = "bash <<'EOF'\nfind . -name \"*.py\"\nEOF\n"
        assert "COST-FULL-TREE-SCAN" in self.rule_ids(hook.strip_payload_bodies(command))

    def test_a_heredoc_piped_into_bash_is_still_classified(self) -> None:
        command = "cat <<'EOF' | bash\npython -m pytest tests\nEOF\n"
        assert "COST-FULL-TEST-SUITE" in self.rule_ids(hook.strip_payload_bodies(command))

    def test_a_stray_double_angle_in_prose_does_not_hide_the_next_line(self) -> None:
        command = 'echo "shift the value << two places"\nfind . -name "*.py"\n'
        assert "COST-FULL-TREE-SCAN" in self.rule_ids(hook.strip_payload_bodies(command))

    def test_an_unterminated_heredoc_does_not_hide_the_rest_of_the_command(self) -> None:
        command = "cat <<'EOF'\npython -m pytest tests\n"
        assert "COST-FULL-TEST-SUITE" in self.rule_ids(hook.strip_payload_bodies(command))

    def test_a_heredoc_marker_inside_a_quoted_string_does_not_hide_the_command_between(self) -> None:
        command = 'echo "a << ZZZ"\nfind . -name "*.py"\nZZZ\n'
        assert "COST-FULL-TREE-SCAN" in self.rule_ids(hook.strip_payload_bodies(command))

    def test_an_apostrophe_before_a_genuine_heredoc_opener_can_now_false_positive(self) -> None:
        """The concrete cost of the new tolerance pinned in ``TestPayloadStrippingSafety``:
        an ordinary documentation heredoc, whose opening line happens to carry an apostrophe
        before the ``<<``, is no longer recognized as a genuine heredoc -- its prose body
        stays visible and, here, that prose itself mentions ``pytest tests``, so this
        previously-silent note-writing command now blocks. Before this fix the body would
        have been stripped and this would not have blocked at all."""
        command = "echo don't care <<'EOF' > NOTE.md\nRun `python -m pytest tests -q` before reporting done.\nEOF\n"
        assert "COST-FULL-TEST-SUITE" in self.rule_ids(hook.strip_payload_bodies(command))

    def test_a_heredoc_marker_inside_a_multiline_quoted_string_does_not_hide_the_command_between(
        self,
    ) -> None:
        command = (
            'echo "first line of a quoted message\n'
            "and a value shifted << ZZZ\n"
            'find . -name "*.py"\n'
            "ZZZ\n"
        )
        assert "COST-FULL-TREE-SCAN" in self.rule_ids(hook.strip_payload_bodies(command))

    def test_a_backslash_escaped_quote_ahead_of_a_heredoc_marker_does_not_hide_the_command_between(
        self,
    ) -> None:
        command = 'echo "she said \\" and a << ZZZ"\nfind . -name "*.py"\nZZZ\n'
        assert "COST-FULL-TREE-SCAN" in self.rule_ids(hook.strip_payload_bodies(command))


class TestHookEndToEnd:
    """Real subprocess invocations of the actual armed/unarmed hook, matching every other
    module in this distribution's own end-to-end convention."""

    def _run(self, sandbox: Path, state_dir: str, command: str, *, armed: bool = True):
        if armed:
            arming.arm("execution_guard", root=sandbox)
        env = {**os.environ, "INTERLOCK_GUARD_STATE_DIR": state_dir}
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
        return subprocess.run(
            [sys.executable, "-B", "-m", "interlock.guard.execution_guard"],
            cwd=str(sandbox), input=payload, capture_output=True, text=True, env=env, check=False,
        )

    def test_unarmed_is_a_silent_no_op(self, sandbox: Path, tmp_path: Path) -> None:
        result = self._run(sandbox, str(tmp_path / "state"), "git worktree add ../new origin/main", armed=False)
        assert result.returncode == 0
        assert result.stdout == ""

    def test_armed_heavy_command_blocks_and_audits_only_the_hash(self, sandbox: Path, tmp_path: Path) -> None:
        state_dir = str(tmp_path / "state")
        command = "git worktree add ../new origin/main"
        result = self._run(sandbox, state_dir, command)
        decision = json.loads(result.stdout)
        assert decision["decision"] == "block"
        sha256 = hook.command_sha256(command)
        assert sha256 in decision["reason"]
        events = (Path(state_dir) / "events.jsonl").read_text(encoding="utf-8")
        assert sha256 in events
        assert command not in events

    def test_armed_safe_command_emits_nothing(self, sandbox: Path, tmp_path: Path) -> None:
        state_dir = str(tmp_path / "state")
        result = self._run(sandbox, state_dir, "python -m pytest tests/test_one.py -q")
        assert result.stdout == ""
        assert not (Path(state_dir) / "events.jsonl").exists()

    def test_armed_heredoc_content_mentioning_a_command_does_not_block(self, sandbox: Path, tmp_path: Path) -> None:
        command = (
            "cat <<'EOF' > NOTE.md\n"
            "Run `python -m pytest tests -q` before reporting done.\n"
            "EOF\n"
        )
        result = self._run(sandbox, str(tmp_path / "state"), command)
        assert result.stdout == "", result.stdout

    def test_armed_heredoc_body_fed_to_bash_still_blocks(self, sandbox: Path, tmp_path: Path) -> None:
        """Independent-review follow-up, driven as a real armed subprocess, not just the
        pure function: a heredoc body a shell will actually execute must still refuse."""
        command = "bash <<'EOF'\nfind . -name \"*.py\"\nEOF\n"
        result = self._run(sandbox, str(tmp_path / "state"), command)
        decision = json.loads(result.stdout)
        assert decision["decision"] == "block"
        assert "COST-FULL-TREE-SCAN" in decision["reason"]

    def test_armed_unterminated_heredoc_still_blocks(self, sandbox: Path, tmp_path: Path) -> None:
        """Independent-review follow-up: an unterminated heredoc must not silently discard
        the expensive command that follows it, driven as a real armed subprocess."""
        command = "cat <<'EOF'\npython -m pytest tests\n"
        result = self._run(sandbox, str(tmp_path / "state"), command)
        decision = json.loads(result.stdout)
        assert decision["decision"] == "block"
        assert "COST-FULL-TEST-SUITE" in decision["reason"]

    def test_armed_heredoc_marker_inside_a_quoted_string_still_blocks(self, sandbox: Path, tmp_path: Path) -> None:
        """Re-review follow-up, driven as a real armed subprocess: a coincidental `<<`/tag
        match inside ordinary quoted prose must not disarm the guard against the real
        command sitting between the two lines that happen to look like a heredoc."""
        command = 'echo "a << ZZZ"\nfind . -name "*.py"\nZZZ\n'
        result = self._run(sandbox, str(tmp_path / "state"), command)
        decision = json.loads(result.stdout)
        assert decision["decision"] == "block"
        assert "COST-FULL-TREE-SCAN" in decision["reason"]

    def test_armed_heredoc_marker_inside_a_multiline_quoted_string_still_blocks(
        self, sandbox: Path, tmp_path: Path
    ) -> None:
        """A third independent review pass, driven as a real armed subprocess: a quoted
        string that opens on one line and does not close until a later one must not let a
        coincidental `<<` in between disarm the guard against the real command sitting
        between it and the tag line that happens to match."""
        command = (
            'echo "first line of a quoted message\n'
            "and a value shifted << ZZZ\n"
            'find . -name "*.py"\n'
            "ZZZ\n"
        )
        result = self._run(sandbox, str(tmp_path / "state"), command)
        decision = json.loads(result.stdout)
        assert decision["decision"] == "block"
        assert "COST-FULL-TREE-SCAN" in decision["reason"]

    def test_armed_backslash_escaped_quote_ahead_of_a_heredoc_marker_still_blocks(
        self, sandbox: Path, tmp_path: Path
    ) -> None:
        """Same review pass, driven as a real armed subprocess: a backslash-escaped quote
        must not be counted as closing a string that is genuinely still open."""
        command = 'echo "she said \\" and a << ZZZ"\nfind . -name "*.py"\nZZZ\n'
        result = self._run(sandbox, str(tmp_path / "state"), command)
        decision = json.loads(result.stdout)
        assert decision["decision"] == "block"
        assert "COST-FULL-TREE-SCAN" in decision["reason"]

    def test_valid_approval_is_consumed_once(self, sandbox: Path, tmp_path: Path) -> None:
        state_dir = str(tmp_path / "state")
        command = "git worktree add ../new origin/main"
        sha256 = hook.command_sha256(command)
        old = os.environ.get("INTERLOCK_GUARD_STATE_DIR")
        os.environ["INTERLOCK_GUARD_STATE_DIR"] = state_dir
        try:
            hook.record_approval(
                sha256,
                reason="explicit user-approved isolation need",
                alternatives="existing worktrees cannot isolate the candidate",
                baseline_plan="retain the accepted detached validation receipt",
                expires_minutes=30,
            )
        finally:
            if old is None:
                os.environ.pop("INTERLOCK_GUARD_STATE_DIR", None)
            else:
                os.environ["INTERLOCK_GUARD_STATE_DIR"] = old
        first = self._run(sandbox, state_dir, command)
        assert first.stdout == ""
        second = self._run(sandbox, state_dir, command)
        assert json.loads(second.stdout)["decision"] == "block"


class TestArmingDiscipline:
    def test_a_fresh_worktree_is_not_armed(self, sandbox: Path) -> None:
        assert arming.is_armed("execution_guard", root=sandbox) is False

    def test_arming_makes_it_armed(self, sandbox: Path) -> None:
        arming.arm("execution_guard", root=sandbox)
        assert arming.is_armed("execution_guard", root=sandbox) is True

    def test_disarm_removes_it(self, sandbox: Path) -> None:
        arming.arm("execution_guard", root=sandbox)
        arming.disarm("execution_guard", root=sandbox)
        assert arming.is_armed("execution_guard", root=sandbox) is False

    def test_unknown_hook_key_raises(self) -> None:
        with pytest.raises(ValueError):
            arming.marker_name_for("does-not-exist")


class TestAtomicWriteSurvivesAConcurrentReader:
    """The approval receipt is a shared target: :func:`record_approval` writes it while a
    concurrent invocation's :func:`consume_approval` may hold it open for read.

    On Windows a rename onto a handle another reader holds -- even a read-only handle -- is
    refused with ``PermissionError`` and ``winerror == 5``. The refusal is transient and says
    nothing about either file's content, so the write must retry rather than fail. The
    platform-dependent proofs below are skipped elsewhere and say so; the contract tests
    above them run everywhere, because an adopter on any platform depends on the two failure
    outcomes sharing one base class.
    """

    WINDOWS_ONLY = pytest.mark.skipif(
        sys.platform != "win32",
        reason="the refusal this retries is a Windows rename-onto-an-open-handle behaviour; "
               "on other platforms the helper is a deliberate pass-through and there is no "
               "refusal to survive",
    )

    @staticmethod
    def _held(target: Path, seconds: float):
        """Open ``target`` for read from a second thread and release it after ``seconds``.
        A real handle, not a patched call: the refusal under test is the platform's."""
        import threading
        import time

        opened = threading.Event()

        def hold() -> None:
            with open(target, "rb"):
                opened.set()
                time.sleep(seconds)

        thread = threading.Thread(target=hold, daemon=True)
        thread.start()
        assert opened.wait(5.0), "the holding thread never opened the target"
        return thread

    @staticmethod
    def _pair(tmp_path: Path, *, target_bytes: bytes = b"before\n") -> tuple[Path, Path]:
        source = tmp_path / "source.tmp"
        source.write_bytes(b"after\n")
        target = tmp_path / "target.json"
        target.write_bytes(target_bytes)
        return source, target

    def test_both_failure_outcomes_share_one_base_so_one_except_clause_catches_both(self) -> None:
        """The asymmetry this asserts against is a real defect, not a hypothetical: a sibling
        implementation of this helper once raised one outcome as an ``OSError`` subclass and
        the other as a ``RuntimeError``, so a caller's ``except OSError`` handled one and let
        the other escape its own error contract."""
        assert issubclass(hook.ReplaceNotApplied, OSError)
        assert issubclass(hook.ReplaceVerificationError, OSError)
        assert issubclass(hook.ReplaceNotApplied, PermissionError)

    def test_the_retry_budget_is_bounded_and_stated(self) -> None:
        assert hook.REPLACE_MAX_ATTEMPTS == 6
        assert hook.REPLACE_BACKOFF_SECONDS == 0.05

    def test_an_uncontended_replace_lands_and_returns_nothing(self, tmp_path: Path) -> None:
        source, target = self._pair(tmp_path)
        assert hook.replace_with_retry_verified(source, target) is None
        assert target.read_bytes() == b"after\n"
        assert not source.exists()

    @WINDOWS_ONLY
    def test_a_bare_replace_under_the_identical_hold_is_refused(self, tmp_path: Path) -> None:
        """The RED the rest of this class is measured against. Without it, a green below
        could mean the hold never reproduced the refusal at all."""
        source, target = self._pair(tmp_path)
        thread = self._held(target, 0.6)
        try:
            with pytest.raises(PermissionError) as caught:
                os.replace(source, target)
            assert caught.value.winerror == 5
        finally:
            thread.join(timeout=10.0)

    @WINDOWS_ONLY
    def test_a_transient_hold_on_the_target_is_survived(self, tmp_path: Path) -> None:
        source, target = self._pair(tmp_path)
        thread = self._held(target, 0.20)
        try:
            hook.replace_with_retry_verified(source, target)
        finally:
            thread.join(timeout=10.0)
        assert target.read_bytes() == b"after\n"

    @WINDOWS_ONLY
    def test_a_hold_outlasting_the_budget_raises_and_leaves_the_target_untouched(
        self, tmp_path: Path,
    ) -> None:
        source, target = self._pair(tmp_path)
        thread = self._held(target, 1.2)
        try:
            with pytest.raises(hook.ReplaceNotApplied):
                hook.replace_with_retry_verified(source, target)
        finally:
            thread.join(timeout=10.0)
        assert target.read_bytes() == b"before\n"

    @WINDOWS_ONLY
    def test_a_write_that_is_already_present_is_reported_as_success_not_as_a_failure(
        self, tmp_path: Path,
    ) -> None:
        """The partial-observability case, reproduced by its observable state rather than by
        the race that produces it: the retries genuinely exhaust against a real refusal, and
        the target already carries exactly what the source held. Forcing the platform to both
        apply a rename and report it refused has no deterministic trigger; what this helper
        owns is the read-back-and-compare that follows, and that is what this proves."""
        source, target = self._pair(tmp_path, target_bytes=b"after\n")
        thread = self._held(target, 1.2)
        try:
            assert hook.replace_with_retry_verified(source, target) is None
        finally:
            thread.join(timeout=10.0)

    @WINDOWS_ONLY
    def test_a_target_that_cannot_be_read_back_raises_the_verification_outcome(
        self, tmp_path: Path,
    ) -> None:
        """A directory standing where the target belongs: the refusal is permanent rather
        than transient, the retries correctly give up, and reading the target back to
        classify the outcome itself fails. The caller is told so explicitly."""
        source = tmp_path / "source.tmp"
        source.write_bytes(b"after\n")
        target = tmp_path / "target.json"
        target.mkdir()
        with pytest.raises(hook.ReplaceVerificationError):
            hook.replace_with_retry_verified(source, target)

    @WINDOWS_ONLY
    def test_an_unreadable_source_with_a_still_renamable_target_degrades_loudly(
        self, tmp_path: Path,
    ) -> None:
        """`ENG-00736`: the file-site silent degradation. A source held under a REAL
        lock that denies read but permits rename (``open(source, "rb")`` fails,
        ``os.replace`` does not) used to make ``replace_with_retry_verified`` return
        exactly as a verified success would, with nothing telling the caller
        verification never happened. Proven against a real held-open lock, not a
        patched call."""
        import ctypes
        import warnings
        from ctypes import wintypes

        source, target = self._pair(tmp_path)
        generic_read = 0x80000000
        file_share_delete = 0x00000004
        open_existing = 3
        file_attribute_normal = 0x80
        create_file = ctypes.windll.kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        handle = create_file(
            str(source), generic_read, file_share_delete, None,
            open_existing, file_attribute_normal, None,
        )
        assert handle not in (0, -1), "CreateFileW failed to acquire the probe lock"
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                hook.replace_with_retry_verified(source, target)
            skipped = [
                w for w in caught
                if issubclass(w.category, hook.ReplaceVerificationSkipped)
            ]
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
        assert target.read_bytes() == b"after\n"
        assert skipped, "no ReplaceVerificationSkipped warning was emitted"

    @WINDOWS_ONLY
    def test_an_uncontended_replace_emits_no_verification_skipped_warning(
        self, tmp_path: Path,
    ) -> None:
        """Negative control for the test above: without it, a copy that always warns
        regardless of contention would pass the positive test for the wrong reason."""
        import warnings

        source, target = self._pair(tmp_path)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            hook.replace_with_retry_verified(source, target)
        skipped = [
            w for w in caught
            if issubclass(w.category, hook.ReplaceVerificationSkipped)
        ]
        assert not skipped, "an ordinary uncontended replace must not warn"

    @WINDOWS_ONLY
    def test_record_approval_survives_a_concurrent_reader_of_its_own_receipt(
        self, tmp_path: Path,
    ) -> None:
        """The production call path, not the helper in isolation."""
        old = os.environ.get("INTERLOCK_GUARD_STATE_DIR")
        os.environ["INTERLOCK_GUARD_STATE_DIR"] = str(tmp_path / "state")
        try:
            sha = "C" * 64
            receipt = hook.record_approval(
                sha, reason="r", alternatives="a", baseline_plan="b", expires_minutes=5,
            )
            thread = self._held(receipt, 0.20)
            try:
                hook.record_approval(
                    sha, reason="r2", alternatives="a2", baseline_plan="b2", expires_minutes=5,
                )
            finally:
                thread.join(timeout=10.0)
            assert json.loads(receipt.read_text(encoding="utf-8"))["reason"] == "r2"
        finally:
            if old is None:
                os.environ.pop("INTERLOCK_GUARD_STATE_DIR", None)
            else:
                os.environ["INTERLOCK_GUARD_STATE_DIR"] = old


class TestExclusiveCreateClaimPrimitive:
    """`ENG-00734` design, layer 1 -- see the identical class in
    ``engineering/tests/test_command_cost_guard_hook.py`` for the full rationale. Kept here
    too because this package ships and tests itself independently: `consume_approval`'s
    claim is `os.open(path, O_CREAT|O_EXCL|O_WRONLY)`, and these are the measured shapes it
    must survive on this platform (`eng00734_probe.py` M3/M4) -- especially the one that
    decides which `except` clause is correct: an existing DIRECTORY at the claim path is
    `PermissionError` errno 13, NOT `FileExistsError`, which is why the implementation
    catches `OSError`.
    """

    @staticmethod
    def _claim(path: Path):
        return os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)

    def test_a_second_claim_in_the_same_process_is_refused_deterministically(self, tmp_path: Path) -> None:
        claim = tmp_path / "claim.json"
        os.close(self._claim(claim))
        with pytest.raises(FileExistsError) as caught:
            self._claim(claim)
        assert caught.value.errno == 17

    def test_a_claim_against_a_file_held_open_by_another_reader_also_refuses(self, tmp_path: Path) -> None:
        claim = tmp_path / "claim.json"
        os.close(self._claim(claim))
        thread = _hold_open(claim, 0.3)
        try:
            with pytest.raises(FileExistsError) as caught:
                self._claim(claim)
            assert caught.value.errno == 17
        finally:
            thread.join(timeout=10.0)

    def test_a_claim_against_an_existing_directory_is_permission_error_not_file_exists_error(
        self, tmp_path: Path,
    ) -> None:
        """The load-bearing shape (design section 4.1): this is why `consume_approval`
        catches `OSError`, not `FileExistsError` -- a narrower catch would let this escape."""
        claim_dir = tmp_path / "claim.json"
        claim_dir.mkdir()
        with pytest.raises(PermissionError) as caught:
            self._claim(claim_dir)
        assert caught.value.errno == 13
        assert not isinstance(caught.value, FileExistsError)

    def test_replace_onto_an_existing_file_succeeds_which_is_why_rename_cannot_be_the_claim(
        self, tmp_path: Path,
    ) -> None:
        source = tmp_path / "source.tmp"
        source.write_bytes(b"after\n")
        target = tmp_path / "target.json"
        target.write_bytes(b"before\n")
        os.replace(source, target)  # succeeds outright -- no exception, no exclusivity
        assert target.read_bytes() == b"after\n"


class TestConcurrentSourceReplaceCanStillSucceedTwice:
    """`ENG-00734` design, layer 2 -- see the identical class in
    ``engineering/tests/test_command_cost_guard_hook.py`` for the full rationale. Drives
    TODAY's `os.replace` primitive directly -- `consume_approval` no longer calls it for the
    claim, only for a best-effort cleanup unlink -- and asserts BOTH racers can succeed, so
    the defect this redesign answers stays in the suite as a measured fact rather than as
    prose (`ENV-TWO-CONCURRENT-OS-REPLACE-CALLS-ONTO-ONE-TARGET-CAN-BOTH-SUCCEED-ON-
    WINDOWS`; M1: 15 of 20 real-process trials).

    Allowed to be concurrent precisely because it asserts the UNSAFE behaviour: a race that
    fails to land makes this fail loudly rather than pass falsely. If every trial refuses,
    the platform's `os.replace` semantics changed and this design's premise needs
    re-reading -- a hard failure here, not a skip, is meant to surface that.
    """

    _CHILD = (
        "import os, sys, time\n"
        "root, racer = sys.argv[1], sys.argv[2]\n"
        "open(os.path.join(root, 'ready.' + racer), 'w').close()\n"
        "go = os.path.join(root, 'go')\n"
        "deadline = time.time() + 30.0\n"
        "while not os.path.exists(go):\n"
        "    if time.time() > deadline:\n"
        "        print('TIMEOUT')\n"
        "        sys.exit(1)\n"
        "try:\n"
        "    os.replace(os.path.join(root, 'source.json'), os.path.join(root, 'target.json'))\n"
        "    print('WIN')\n"
        "except OSError as error:\n"
        "    print('LOSE', type(error).__name__)\n"
    )

    def _race(self, root: Path, racers: int = 2) -> int:
        """One trial: real processes, released by a filesystem barrier. Returns how many
        observed their own `os.replace` succeed."""
        (root / "source.json").write_text('{"uses_remaining": 1}\n', encoding="utf-8")
        (root / "target.json").write_text("{}\n", encoding="utf-8")
        ids = [f"r{index}" for index in range(racers)]
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", self._CHILD, str(root), racer],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            for racer in ids
        ]
        deadline = time.time() + 15.0
        while time.time() < deadline:
            if all((root / f"ready.{racer}").exists() for racer in ids):
                break
        else:
            raise RuntimeError("racers never all reported ready")
        (root / "go").write_text("go", encoding="utf-8")
        winners = 0
        for proc in procs:
            out, err = proc.communicate(timeout=30)
            assert proc.returncode == 0, err
            if out.startswith("WIN"):
                winners += 1
        return winners

    def test_two_real_processes_can_both_report_success_replacing_one_source(
        self, tmp_path: Path,
    ) -> None:
        trials = 10
        winner_counts = []
        for trial in range(trials):
            root = tmp_path / f"trial{trial}"
            root.mkdir()
            winner_counts.append(self._race(root))
        assert 2 in winner_counts, (
            f"expected at least one of {trials} trials to show both racers win "
            f"(measured M1: 15/20); observed {winner_counts} -- either this platform's "
            "os.replace semantics changed, or something masked the race"
        )
