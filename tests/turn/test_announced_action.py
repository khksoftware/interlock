# SPDX-License-Identifier: Apache-2.0
"""Tests for `interlock/turn/announced_action.py`, including a battery of legitimate
sentence shapes that must never be blocked."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from interlock.turn import session_record as sr

from .conftest import run_hook_subprocess, write_transcript

HOOK_PATH = Path(__file__).resolve().parent.parent.parent / "src" / "interlock" / "turn" / "announced_action.py"
_spec = importlib.util.spec_from_file_location("announced_action", HOOK_PATH)
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)


ANNOUNCED_SHAPES = (
    "I'll dispatch the reviewer now.",
    "I'm going to commit this next.",
    "Let me push this change.",
    "Dispatching the review stream now.",
    "Next, I will run the tests.",
)

LEGITIMATE_SHAPES = (
    "I'll relay that to you once it's done.",
    "This is blocked on your go-ahead.",
    "I already committed this earlier.",
    "The tests passed.",
    "Splitting it left a head of zero bytes.",
    "Folding the file means moving the list.",
    "Deleting it would destroy that.",
    "I won't do that without approval.",
    "Once you approve, I'll proceed.",
    "I dispatched the reviewer and it returned clean.",
    "Is this the right approach?",
    "I'll stand by for your answer.",
)


class TestAnnouncedActions:
    def test_every_announced_shape_is_caught(self):
        for sentence in ANNOUNCED_SHAPES:
            assert hook.announced_actions(sentence), f"missed: {sentence!r}"

    def test_every_legitimate_shape_is_not_caught(self):
        for sentence in LEGITIMATE_SHAPES:
            assert not hook.announced_actions(sentence), f"false positive: {sentence!r}"


class TestC2BlockerCorroboration:
    OPEN = frozenset({"PROJ-1"})

    def test_c2_b01_one_argument_call_remains_callable(self):
        assert hook.announced_actions("The tests passed.") == []

    def test_c2_b02_one_argument_call_retains_bare_blocker(self):
        assert hook.announced_actions("I'll dispatch once PROJ-1.")

    def test_c2_b03_second_positional_argument_is_refused(self):
        with pytest.raises(TypeError):
            hook.announced_actions("I'll dispatch once PROJ-1.", self.OPEN)

    def test_c2_b04_once_open_id_suppresses(self):
        assert not hook.announced_actions("I'll dispatch once PROJ-1.", open_row_ids=self.OPEN)

    def test_c2_b05_once_fabricated_id_retains(self):
        assert hook.announced_actions("I'll dispatch once PROJ-9.", open_row_ids=self.OPEN)

    def test_c2_b06_await_open_id_suppresses(self):
        assert not hook.announced_actions("I'll dispatch await PROJ-1.", open_row_ids=self.OPEN)

    def test_c2_b07_await_fabricated_id_retains(self):
        assert hook.announced_actions("I'll dispatch await PROJ-9.", open_row_ids=self.OPEN)

    def test_c2_b08_waiting_on_open_id_suppresses(self):
        assert not hook.announced_actions("I'll dispatch waiting on PROJ-1.", open_row_ids=self.OPEN)

    def test_c2_b09_waiting_on_fabricated_id_retains(self):
        assert hook.announced_actions("I'll dispatch waiting on PROJ-9.", open_row_ids=self.OPEN)

    def test_c2_b10_waiting_for_open_id_suppresses(self):
        assert not hook.announced_actions("I'll dispatch waiting for PROJ-1.", open_row_ids=self.OPEN)

    def test_c2_b11_waiting_for_fabricated_id_retains(self):
        assert hook.announced_actions("I'll dispatch waiting for PROJ-9.", open_row_ids=self.OPEN)

    def test_c2_b12_waits_on_open_id_suppresses(self):
        assert not hook.announced_actions("I'll dispatch but it waits on PROJ-1.", open_row_ids=self.OPEN)

    def test_c2_b13_waits_on_fabricated_id_retains(self):
        assert hook.announced_actions("I'll dispatch but it waits on PROJ-9.", open_row_ids=self.OPEN)

    def test_c2_b14_blocked_on_open_id_suppresses(self):
        assert not hook.announced_actions("I'll dispatch blocked on PROJ-1.", open_row_ids=self.OPEN)

    def test_c2_b15_blocked_on_fabricated_id_retains(self):
        assert hook.announced_actions("I'll dispatch blocked on PROJ-9.", open_row_ids=self.OPEN)

    def test_c2_b16_terminal_id_retains(self):
        node = {"queue": [{"id": "PROJ-1", "status": "closed"}]}
        assert hook.announced_actions("I'll dispatch once PROJ-1.", open_row_ids=sr.open_row_ids(node))

    def test_c2_b17_absent_record_retains(self, tmp_path):
        ids = _open_ids_from_record(tmp_path / "missing.json")
        assert hook.announced_actions("I'll dispatch once PROJ-1.", open_row_ids=ids)

    def test_c2_b18_unreadable_record_retains(self, tmp_path):
        ids = _open_ids_from_record(tmp_path)
        assert hook.announced_actions("I'll dispatch once PROJ-1.", open_row_ids=ids)

    def test_c2_b19_malformed_json_record_retains(self, tmp_path):
        path = tmp_path / "record.json"
        path.write_text("not json", encoding="utf-8")
        assert hook.announced_actions("I'll dispatch once PROJ-1.", open_row_ids=_open_ids_from_record(path))

    def test_c2_b20_id_case_normalization_corresponds(self):
        assert not hook.announced_actions("I'll dispatch once proj-1.", open_row_ids=self.OPEN)

    def test_c2_b21_partial_id_does_not_fullmatch(self):
        assert hook.announced_actions("I'll dispatch once PROJ-1-extra.", open_row_ids=self.OPEN)

    def test_c2_b22_real_id_before_clause_cannot_launder(self):
        assert hook.announced_actions("I'll dispatch PROJ-1 once PROJ-9.", open_row_ids=self.OPEN)

    def test_c2_b23_real_id_after_clause_boundary_cannot_launder(self):
        assert hook.announced_actions("I'll dispatch once PROJ-9, then PROJ-1.", open_row_ids=self.OPEN)

    def test_c2_b24_real_then_fabricated_in_clause_cannot_launder(self):
        assert hook.announced_actions("I'll dispatch once PROJ-1 PROJ-9.", open_row_ids=self.OPEN)

    def test_c2_b25_fabricated_then_real_in_clause_cannot_launder(self):
        assert hook.announced_actions("I'll dispatch once PROJ-9 PROJ-1.", open_row_ids=self.OPEN)

    def test_c2_b26_wrong_platform_id_cannot_suppress(self):
        document = {"platforms": [
            {"platform": "other", "queue": [{"id": "PROJ-1", "status": "queued"}]},
            {"platform": "default", "queue": []},
        ]}
        ids = sr.open_row_ids(sr.platform_node(document, platform="default"))
        assert hook.announced_actions("I'll dispatch once PROJ-1.", open_row_ids=ids)

    def test_c2_b27_malformed_id_pattern_retains_without_raising(self):
        assert hook.announced_actions("I'll dispatch once PROJ-1.", open_row_ids=self.OPEN, id_pattern="[")

    def test_c2_b28_after_you_remains_unconditional(self):
        assert not hook.announced_actions("I'll dispatch after you confirm.")

    def test_c2_b29_when_you_remains_unconditional(self):
        assert not hook.announced_actions("I'll dispatch when you confirm.")

    def test_c2_b30_pending_your_remains_unconditional(self):
        assert not hook.announced_actions("I'll dispatch pending your approval.")

    def test_c2_b31_your_decision_remains_unconditional(self):
        assert not hook.announced_actions("I'll dispatch after your decision.")


class TestC3PacketBCorrections:
    OPEN = frozenset({"PROJ-1"})

    def test_c3_b32_awaiting_open_id_suppresses(self):
        assert not hook.announced_actions("I'll dispatch awaiting PROJ-1.", open_row_ids=self.OPEN)

    def test_c3_b33_awaiting_fabricated_id_retains(self):
        assert hook.announced_actions("I'll dispatch awaiting PROJ-9.", open_row_ids=self.OPEN)

    def test_c3_b34_awaits_open_id_suppresses(self):
        assert not hook.announced_actions("I'll dispatch and it awaits PROJ-1.", open_row_ids=self.OPEN)

    def test_c3_b35_awaits_fabricated_id_retains(self):
        assert hook.announced_actions("I'll dispatch and it awaits PROJ-9.", open_row_ids=self.OPEN)

    def test_c3_b36_awaited_open_id_suppresses(self):
        assert not hook.announced_actions("I'll dispatch after it awaited PROJ-1.", open_row_ids=self.OPEN)

    def test_c3_b37_awaited_fabricated_id_retains(self):
        assert hook.announced_actions("I'll dispatch after it awaited PROJ-9.", open_row_ids=self.OPEN)

    def test_c3_b38_wait_on_open_id_suppresses(self):
        assert not hook.announced_actions("I'll dispatch but I wait on PROJ-1.", open_row_ids=self.OPEN)

    def test_c3_b39_wait_on_fabricated_id_retains(self):
        assert hook.announced_actions("I'll dispatch but I wait on PROJ-9.", open_row_ids=self.OPEN)

    def test_c3_b40_await_you_open_id_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch await you on PROJ-1.", open_row_ids=self.OPEN)

    def test_c3_b41_await_your_response_fabricated_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch await your response on PROJ-9.", open_row_ids=self.OPEN)

    def test_c3_b42_awaiting_you_open_id_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch awaiting you on PROJ-1.", open_row_ids=self.OPEN)

    def test_c3_b43_awaiting_your_response_fabricated_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch awaiting your response on PROJ-9.", open_row_ids=self.OPEN)

    def test_c3_b44_awaits_you_open_id_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch and it awaits you on PROJ-1.", open_row_ids=self.OPEN)

    def test_c3_b45_awaits_your_decision_fabricated_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch and it awaits your decision on PROJ-9.", open_row_ids=self.OPEN)

    def test_c3_b46_awaited_you_open_id_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch after I awaited you on PROJ-1.", open_row_ids=self.OPEN)

    def test_c3_b47_awaited_your_response_fabricated_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch after I awaited your response on PROJ-9.", open_row_ids=self.OPEN)

    def test_c3_b48_wait_on_you_open_id_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch but I wait on you for PROJ-1.", open_row_ids=self.OPEN)

    def test_c3_b49_wait_on_your_decision_fabricated_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch but I wait on your decision for PROJ-9.", open_row_ids=self.OPEN)

    def test_c3_b50_waits_on_you_open_id_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch but it waits on you for PROJ-1.", open_row_ids=self.OPEN)

    def test_c3_b51_waits_on_your_decision_fabricated_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch but it waits on your decision for PROJ-9.", open_row_ids=self.OPEN)

    def test_c3_b52_once_you_open_id_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch once you resolve PROJ-1.", open_row_ids=self.OPEN)

    def test_c3_b53_once_your_decision_fabricated_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch once your decision resolves PROJ-9.", open_row_ids=self.OPEN)

    def test_c3_b54_waiting_on_you_open_id_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch waiting on you for PROJ-1.", open_row_ids=self.OPEN)

    def test_c3_b55_waiting_on_your_response_fabricated_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch waiting on your response for PROJ-9.", open_row_ids=self.OPEN)

    def test_c3_b56_waiting_for_you_open_id_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch waiting for you on PROJ-1.", open_row_ids=self.OPEN)

    def test_c3_b57_waiting_for_your_decision_fabricated_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch waiting for your decision on PROJ-9.", open_row_ids=self.OPEN)

    def test_c3_b58_blocked_on_you_open_id_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch blocked on you for PROJ-1.", open_row_ids=self.OPEN)

    def test_c3_b59_blocked_on_your_direction_fabricated_is_operator_contingency(self):
        assert not hook.announced_actions("I'll dispatch blocked on your direction for PROJ-9.", open_row_ids=self.OPEN)

    def test_c3_b60_immediate_backtick_open_id_suppresses(self):
        assert not hook.announced_actions("I'll dispatch once `PROJ-1`.", open_row_ids=self.OPEN)

    def test_c3_b61_immediate_backtick_fabricated_id_retains(self):
        assert hook.announced_actions("I'll dispatch once `PROJ-9`.", open_row_ids=self.OPEN)

    def test_c3_b62_generic_inline_code_cannot_corroborate_or_promote(self):
        text = "I'll dispatch once `example` PROJ-1."
        assert hook.announced_actions(text, open_row_ids=self.OPEN)

    def test_c3_b63_quote_line_blocker_example_remains_removed(self):
        text = "The current state is settled.\n> I'll dispatch once PROJ-1."
        assert not hook.announced_actions(text, open_row_ids=self.OPEN)

    def test_c3_b64_fenced_blocker_example_remains_removed(self):
        text = "The current state is settled.\n```\nI'll dispatch once PROJ-1.\n```"
        assert not hook.announced_actions(text, open_row_ids=self.OPEN)


def _open_ids_from_record(path):
    document = sr.load_record(path)
    node = sr.platform_node(document, platform="default") if document else None
    return sr.open_row_ids(node)


def _assistant_text_entry(text):
    return {"type": "assistant", "isSidechain": False, "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def _assistant_tool_entry():
    return {"type": "assistant", "isSidechain": False, "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "x", "input": {}}]}}


def test_final_message_announcing_and_not_acting_blocks(sandbox):
    transcript = write_transcript(sandbox, [_assistant_text_entry("I'll dispatch the reviewer now.")])
    proc = run_hook_subprocess("announced_action.py", sandbox, {"transcript_path": str(transcript), "stop_hook_active": False})
    assert proc.returncode == 0, proc.stderr
    decision = json.loads(proc.stdout)
    assert decision["decision"] == "block"


def test_final_message_with_a_tool_call_never_blocks(sandbox):
    transcript = write_transcript(sandbox, [_assistant_tool_entry()])
    proc = run_hook_subprocess("announced_action.py", sandbox, {"transcript_path": str(transcript), "stop_hook_active": False})
    assert proc.stdout.strip() == ""


def test_a_completed_report_never_blocks(sandbox):
    transcript = write_transcript(sandbox, [_assistant_text_entry("I already committed this and pushed it.")])
    proc = run_hook_subprocess("announced_action.py", sandbox, {"transcript_path": str(transcript), "stop_hook_active": False})
    assert proc.stdout.strip() == ""


def test_stop_hook_active_short_circuits(sandbox):
    transcript = write_transcript(sandbox, [_assistant_text_entry("I'll dispatch the reviewer now.")])
    proc = run_hook_subprocess("announced_action.py", sandbox, {"transcript_path": str(transcript), "stop_hook_active": True})
    assert proc.stdout.strip() == ""


def test_sidechain_message_is_never_checked(sandbox):
    entry = _assistant_text_entry("I'll dispatch the reviewer now.")
    entry["isSidechain"] = True
    transcript = write_transcript(sandbox, [entry])
    proc = run_hook_subprocess("announced_action.py", sandbox, {"transcript_path": str(transcript), "stop_hook_active": False})
    assert proc.stdout.strip() == ""


def test_unarmed_worktree_never_blocks_even_on_a_clear_announcement(sandbox):
    transcript = write_transcript(sandbox, [_assistant_text_entry("I'll dispatch the reviewer now.")])
    proc = run_hook_subprocess(
        "announced_action.py", sandbox, {"transcript_path": str(transcript), "stop_hook_active": False}, armed=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""
