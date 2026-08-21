# SPDX-License-Identifier: Apache-2.0
"""Tests for `interlock/turn/user_prompt_submit.py`."""
from __future__ import annotations

import json

from interlock.turn import outstanding

from .conftest import run_hook_subprocess


def test_ordinary_prompt_gets_the_base_reminder(tmp_path, sandbox):
    registry_path = tmp_path / "reg.json"
    proc = run_hook_subprocess(
        "user_prompt_submit.py", sandbox, {"prompt": "just a normal message"},
        env={"INTERLOCK_OUTSTANDING_REGISTRY_PATH": str(registry_path)},
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "ROLE LABEL" in context
    assert "HIGH-RISK" not in context


def test_resumption_command_escalates(tmp_path, sandbox):
    registry_path = tmp_path / "reg.json"
    proc = run_hook_subprocess(
        "user_prompt_submit.py", sandbox, {"prompt": "/resume"},
        env={"INTERLOCK_OUTSTANDING_REGISTRY_PATH": str(registry_path)},
    )
    payload = json.loads(proc.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "HIGH-RISK BOUNDARY" in context
    assert "resumption command" in context


def test_outstanding_agents_escalate_and_are_named(tmp_path, sandbox):
    registry_path = tmp_path / "reg.json"
    outstanding.record_start(registry_path, {"agent_id": "worker-1", "description": "run the tests"})
    proc = run_hook_subprocess(
        "user_prompt_submit.py", sandbox, {"prompt": "ordinary follow-up"},
        env={"INTERLOCK_OUTSTANDING_REGISTRY_PATH": str(registry_path)},
    )
    payload = json.loads(proc.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "HIGH-RISK BOUNDARY" in context
    assert "worker-1" in context
    assert "run the tests" in context


def test_stale_entries_are_pruned_and_not_reminded(tmp_path, sandbox):
    registry_path = tmp_path / "reg.json"
    registry_path.write_text(json.dumps([{"id": "old", "description": "stale", "started_at": 0}]), encoding="utf-8")
    proc = run_hook_subprocess(
        "user_prompt_submit.py", sandbox, {"prompt": "ordinary follow-up"},
        env={"INTERLOCK_OUTSTANDING_REGISTRY_PATH": str(registry_path)},
    )
    payload = json.loads(proc.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "old" not in context
    assert "HIGH-RISK" not in context


def test_malformed_stdin_never_crashes(sandbox):
    import subprocess
    import sys
    from pathlib import Path
    from interlock.turn import arming
    arming.arm("user_prompt_submit", root=sandbox)
    hook_path = Path(__file__).resolve().parent.parent.parent / "src" / "interlock" / "turn" / "user_prompt_submit.py"
    proc = subprocess.run([sys.executable, str(hook_path)], input="not json", capture_output=True, text=True, cwd=str(sandbox))
    assert proc.returncode == 0, proc.stderr


def test_unarmed_worktree_emits_no_reminder_at_all(tmp_path, sandbox):
    registry_path = tmp_path / "reg.json"
    proc = run_hook_subprocess(
        "user_prompt_submit.py", sandbox, {"prompt": "/resume"},
        env={"INTERLOCK_OUTSTANDING_REGISTRY_PATH": str(registry_path)},
        armed=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""
