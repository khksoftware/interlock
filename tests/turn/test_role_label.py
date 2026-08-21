# SPDX-License-Identifier: Apache-2.0
"""Tests for `interlock/turn/role_label.py`."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from .conftest import run_hook_subprocess, write_transcript

HOOK_PATH = Path(__file__).resolve().parent.parent.parent / "src" / "interlock" / "turn" / "role_label.py"
_spec = importlib.util.spec_from_file_location("role_label", HOOK_PATH)
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)


class TestClassify:
    def test_valid_supervisor_label_passes(self):
        assert hook.classify("[Supervisor] doing the thing") is None

    def test_valid_worker_label_passes(self):
        assert hook.classify("[Worker] doing the thing") is None

    def test_missing_label_fails(self):
        assert "no role label" in hook.classify("doing the thing")

    def test_unrecognised_label_fails(self):
        assert "unrecognized" in hook.classify("[Nonsense] doing the thing")

    def test_two_labels_in_one_message_fails(self):
        reason = hook.classify("[Supervisor] [Worker] doing the thing")
        assert "two role labels" in reason


class TestFirstMessageChannel:
    def test_supervisor_first_message_is_fine(self):
        assert hook.first_message_wrong_channel_failure(["[Supervisor] hi"]) is None

    def test_worker_first_message_is_a_channel_violation(self):
        reason = hook.first_message_wrong_channel_failure(["[Worker] hi"])
        assert reason is not None
        assert "reserved to" in reason

    def test_empty_texts_is_fine(self):
        assert hook.first_message_wrong_channel_failure([]) is None


# --- end-to-end (real subprocess) ---------------------------------------------------

def _assistant_entry(text, sidechain=False):
    return {"type": "assistant", "isSidechain": sidechain, "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def _user_entry():
    return {"type": "user", "message": {"role": "user", "content": "hello"}}


def test_correctly_labelled_turn_never_blocks(sandbox):
    transcript = write_transcript(sandbox, [_user_entry(), _assistant_entry("[Supervisor] all good")])
    proc = run_hook_subprocess("role_label.py", sandbox, {"transcript_path": str(transcript), "stop_hook_active": False})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_missing_label_blocks(sandbox):
    transcript = write_transcript(sandbox, [_user_entry(), _assistant_entry("just doing stuff, no label")])
    proc = run_hook_subprocess("role_label.py", sandbox, {"transcript_path": str(transcript), "stop_hook_active": False})
    decision = json.loads(proc.stdout)
    assert decision["decision"] == "block"


def test_worker_label_answering_first_blocks_on_channel(sandbox):
    transcript = write_transcript(sandbox, [_user_entry(), _assistant_entry("[Worker] answering the operator directly")])
    proc = run_hook_subprocess("role_label.py", sandbox, {"transcript_path": str(transcript), "stop_hook_active": False})
    decision = json.loads(proc.stdout)
    assert decision["decision"] == "block"
    assert "reserved to" in decision["reason"]


def test_sidechain_messages_are_never_checked(sandbox):
    transcript = write_transcript(sandbox, [_user_entry(), _assistant_entry("no label here", sidechain=True)])
    proc = run_hook_subprocess("role_label.py", sandbox, {"transcript_path": str(transcript), "stop_hook_active": False})
    assert proc.stdout.strip() == ""


def test_stop_hook_active_short_circuits(sandbox):
    transcript = write_transcript(sandbox, [_user_entry(), _assistant_entry("no label here")])
    proc = run_hook_subprocess("role_label.py", sandbox, {"transcript_path": str(transcript), "stop_hook_active": True})
    assert proc.stdout.strip() == ""


def test_custom_labels_are_honoured(sandbox):
    transcript = write_transcript(sandbox, [_user_entry(), _assistant_entry("[Lead] all good")])
    proc = run_hook_subprocess(
        "role_label.py", sandbox, {"transcript_path": str(transcript), "stop_hook_active": False},
        env={"INTERLOCK_SUPERVISOR_LABEL": "[Lead]", "INTERLOCK_WORKER_LABEL": "[Contributor]"},
    )
    assert proc.stdout.strip() == ""


def test_unarmed_worktree_never_blocks_even_on_a_missing_label(sandbox):
    transcript = write_transcript(sandbox, [_user_entry(), _assistant_entry("no label here at all")])
    proc = run_hook_subprocess(
        "role_label.py", sandbox, {"transcript_path": str(transcript), "stop_hook_active": False}, armed=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""
