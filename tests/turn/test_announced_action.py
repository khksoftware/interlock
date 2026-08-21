# SPDX-License-Identifier: Apache-2.0
"""Tests for `interlock/turn/announced_action.py`, including a battery of legitimate
sentence shapes that must never be blocked."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

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
