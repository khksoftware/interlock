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

import pytest

from interlock.guard import arming, execution_guard as hook


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
