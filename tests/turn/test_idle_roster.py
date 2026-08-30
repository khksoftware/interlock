# SPDX-License-Identifier: Apache-2.0
"""End-to-end tests for `interlock/turn/idle_roster.py`, driven as a real subprocess
against a real fixture repository -- nothing here is mocked."""
from __future__ import annotations

import json

from .conftest import run_hook_subprocess, write_session_record, write_transcript


def test_empty_roster_with_ready_row_blocks(sandbox):
    """RED: a verified-empty roster while a sequenced, unblocked row reads `queued`."""
    write_session_record(
        sandbox, roster={"state": "none", "entries": []},
        queue=[{"id": "PROJ-1", "status": "queued", "sequenced": True}],
    )
    proc = run_hook_subprocess("idle_roster.py", sandbox, {"stop_hook_active": False})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip(), "expected a block decision"
    decision = json.loads(proc.stdout)
    assert decision["decision"] == "block"
    assert "PROJ-1" in decision["reason"]


def test_non_empty_roster_never_blocks(sandbox):
    """GREEN counterpart: same ready row, but the roster already carries an entry."""
    write_session_record(
        sandbox, roster={"state": "enumerated", "entries": [{"id": "worker-a"}]},
        queue=[{"id": "PROJ-1", "status": "queued", "sequenced": True}],
    )
    proc = run_hook_subprocess("idle_roster.py", sandbox, {"stop_hook_active": False})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_unsequenced_row_never_blocks(sandbox):
    write_session_record(
        sandbox, roster={"state": "none", "entries": []},
        queue=[{"id": "PROJ-1", "status": "queued", "sequenced": False}],
    )
    proc = run_hook_subprocess("idle_roster.py", sandbox, {"stop_hook_active": False})
    assert proc.stdout.strip() == ""


def test_blocked_row_never_blocks(sandbox):
    write_session_record(
        sandbox, roster={"state": "none", "entries": []},
        queue=[{"id": "PROJ-1", "status": "queued", "sequenced": True, "blocked_on": "PROJ-0"}],
    )
    proc = run_hook_subprocess("idle_roster.py", sandbox, {"stop_hook_active": False})
    assert proc.stdout.strip() == ""


def test_exempted_row_never_blocks(sandbox):
    exemptions_path = sandbox / "exemptions.json"
    exemptions_path.write_text(json.dumps({"PROJ-1": "session-boundary work"}), encoding="utf-8")
    write_session_record(
        sandbox, roster={"state": "none", "entries": []},
        queue=[{"id": "PROJ-1", "status": "queued", "sequenced": True}],
    )
    proc = run_hook_subprocess(
        "idle_roster.py", sandbox, {"stop_hook_active": False},
        env={"INTERLOCK_SESSION_BOUNDARY_ROWS_PATH": "exemptions.json"},
    )
    assert proc.stdout.strip() == ""


def test_exempted_row_via_shared_interlock_json_never_blocks(sandbox):
    """The one setting `interlock.turn.config` reads from the SHARED `interlock.json`
    file rather than only an environment variable -- see that module's own docstring."""
    (sandbox / "interlock.json").write_text(
        json.dumps({"turn": {"session_boundary_rows": {"PROJ-1": "session-boundary work"}}}),
        encoding="utf-8",
    )
    write_session_record(
        sandbox, roster={"state": "none", "entries": []},
        queue=[{"id": "PROJ-1", "status": "queued", "sequenced": True}],
    )
    proc = run_hook_subprocess("idle_roster.py", sandbox, {"stop_hook_active": False})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_quiescing_command_suppresses_the_check(sandbox):
    write_session_record(
        sandbox, roster={"state": "none", "entries": []},
        queue=[{"id": "PROJ-1", "status": "queued", "sequenced": True}],
    )
    transcript = write_transcript(sandbox, [{"isSidechain": False, "message": "<command-name>/wrap-up</command-name>"}])
    proc = run_hook_subprocess("idle_roster.py", sandbox, {"transcript_path": str(transcript), "stop_hook_active": False})
    assert proc.stdout.strip() == ""


def test_stop_hook_active_short_circuits(sandbox):
    write_session_record(
        sandbox, roster={"state": "none", "entries": []},
        queue=[{"id": "PROJ-1", "status": "queued", "sequenced": True}],
    )
    proc = run_hook_subprocess("idle_roster.py", sandbox, {"stop_hook_active": True})
    assert proc.stdout.strip() == ""


def test_repo_with_no_session_record_is_a_scope_miss(sandbox):
    proc = run_hook_subprocess("idle_roster.py", sandbox, {"stop_hook_active": False})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_custom_session_record_path_is_honoured(sandbox):
    write_session_record(
        sandbox, roster={"state": "none", "entries": []},
        queue=[{"id": "PROJ-1", "status": "queued", "sequenced": True}],
        relative_path="custom/where/record.json",
    )
    proc = run_hook_subprocess(
        "idle_roster.py", sandbox, {"stop_hook_active": False},
        env={"INTERLOCK_SESSION_RECORD_PATH": "custom/where/record.json"},
    )
    decision = json.loads(proc.stdout)
    assert decision["decision"] == "block"


def test_c2_d01_idle_roster_uses_configured_unique_platform(sandbox):
    document = {"platforms": [
        {
            "platform": "other",
            "roster": {"state": "enumerated", "entries": [{"id": "worker-a"}]},
            "queue": [],
        },
        {
            "platform": "default",
            "roster": {"state": "none", "entries": []},
            "queue": [{"id": "PROJ-1", "status": "queued", "sequenced": True}],
        },
    ]}
    path = sandbox / ".interlock" / "session_record.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    proc = run_hook_subprocess("idle_roster.py", sandbox, {"stop_hook_active": False})
    decision = json.loads(proc.stdout)
    assert decision["decision"] == "block"


def test_c2_d02_unselected_ready_row_cannot_trigger_idle_roster(sandbox):
    document = {"platforms": [
        {
            "platform": "other",
            "roster": {"state": "none", "entries": []},
            "queue": [{"id": "PROJ-1", "status": "queued", "sequenced": True}],
        },
        {
            "platform": "default",
            "roster": {"state": "none", "entries": []},
            "queue": [],
        },
    ]}
    path = sandbox / ".interlock" / "session_record.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    proc = run_hook_subprocess("idle_roster.py", sandbox, {"stop_hook_active": False})
    assert proc.stdout.strip() == ""


def test_unarmed_worktree_never_blocks_even_with_a_ready_row_and_empty_roster(sandbox):
    write_session_record(
        sandbox, roster={"state": "none", "entries": []},
        queue=[{"id": "PROJ-1", "status": "queued", "sequenced": True}],
    )
    proc = run_hook_subprocess("idle_roster.py", sandbox, {"stop_hook_active": False}, armed=False)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""
