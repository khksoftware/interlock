# SPDX-License-Identifier: Apache-2.0
"""Tests for `interlock.turn.outstanding` and the `subagent_start.py` / `subagent_stop.py`
hooks that share it."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from interlock.turn import outstanding

from .conftest import run_hook_subprocess


def test_record_start_adds_an_entry(tmp_path):
    path = tmp_path / "registry.json"
    outstanding.record_start(path, {"agent_id": "a1", "description": "do the thing"})
    entries = json.loads(path.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["id"] == "a1"
    assert entries[0]["description"] == "do the thing"
    assert "started_at" in entries[0]


def test_record_start_replaces_an_existing_entry_for_the_same_id(tmp_path):
    path = tmp_path / "registry.json"
    outstanding.record_start(path, {"agent_id": "a1", "description": "first"})
    outstanding.record_start(path, {"agent_id": "a1", "description": "second"})
    entries = json.loads(path.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["description"] == "second"


def test_record_start_with_no_recognisable_id_is_a_noop(tmp_path):
    path = tmp_path / "registry.json"
    outstanding.record_start(path, {"unrelated": "field"})
    assert not path.exists()


def test_record_start_accepts_alternate_key_casings(tmp_path):
    path = tmp_path / "registry.json"
    outstanding.record_start(path, {"agentId": "a2", "task": "something"})
    entries = json.loads(path.read_text(encoding="utf-8"))
    assert entries[0]["id"] == "a2"


def test_record_stop_removes_the_matching_entry(tmp_path):
    path = tmp_path / "registry.json"
    outstanding.record_start(path, {"agent_id": "a1", "description": "x"})
    outstanding.record_start(path, {"agent_id": "a2", "description": "y"})
    outstanding.record_stop(path, {"agent_id": "a1"})
    entries = json.loads(path.read_text(encoding="utf-8"))
    assert [e["id"] for e in entries] == ["a2"]


def test_record_stop_on_missing_file_is_a_noop(tmp_path):
    path = tmp_path / "does-not-exist.json"
    outstanding.record_stop(path, {"agent_id": "a1"})  # must not raise
    assert not path.exists()


def test_prune_and_load_drops_stale_entries(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps([
        {"id": "old", "description": "stale", "started_at": 0},
        {"id": "new", "description": "fresh", "started_at": __import__("time").time()},
    ]), encoding="utf-8")
    fresh = outstanding.prune_and_load(path, stale_seconds=6 * 60 * 60)
    assert [e["id"] for e in fresh] == ["new"]
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert [e["id"] for e in on_disk] == ["new"]


def test_prune_and_load_missing_file_returns_empty(tmp_path):
    assert outstanding.prune_and_load(tmp_path / "missing.json", stale_seconds=100) == []


def test_prune_and_load_malformed_json_returns_empty(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text("not json", encoding="utf-8")
    assert outstanding.prune_and_load(path, stale_seconds=100) == []


# --- hook-level end-to-end (real subprocess) ---------------------------------

def test_subagent_start_hook_writes_the_registry(tmp_path, sandbox):
    registry_path = tmp_path / "reg.json"
    proc = run_hook_subprocess(
        "subagent_start.py", sandbox,
        {"agent_id": "worker-1", "description": "run the tests"},
        env={"INTERLOCK_OUTSTANDING_REGISTRY_PATH": str(registry_path)},
    )
    assert proc.returncode == 0, proc.stderr
    entries = json.loads(registry_path.read_text(encoding="utf-8"))
    assert entries[0]["id"] == "worker-1"


def test_subagent_stop_hook_clears_the_entry(tmp_path, sandbox):
    registry_path = tmp_path / "reg.json"
    env = {"INTERLOCK_OUTSTANDING_REGISTRY_PATH": str(registry_path)}
    run_hook_subprocess("subagent_start.py", sandbox, {"agent_id": "worker-1", "description": "x"}, env=env)
    proc = run_hook_subprocess("subagent_stop.py", sandbox, {"agent_id": "worker-1"}, env=env)
    assert proc.returncode == 0, proc.stderr
    entries = json.loads(registry_path.read_text(encoding="utf-8"))
    assert entries == []


def test_subagent_start_hook_never_crashes_on_malformed_stdin(sandbox):
    import subprocess
    from interlock.turn import arming
    arming.arm("subagent_start", root=sandbox)
    hook_path = Path(__file__).resolve().parent.parent.parent / "src" / "interlock" / "turn" / "subagent_start.py"
    proc = subprocess.run([sys.executable, str(hook_path)], input="not json", capture_output=True, text=True, cwd=str(sandbox))
    assert proc.returncode == 0, proc.stderr


def test_subagent_start_hook_is_a_silent_noop_when_unarmed(tmp_path, sandbox):
    registry_path = tmp_path / "reg.json"
    proc = run_hook_subprocess(
        "subagent_start.py", sandbox,
        {"agent_id": "worker-1", "description": "run the tests"},
        env={"INTERLOCK_OUTSTANDING_REGISTRY_PATH": str(registry_path)},
        armed=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert not registry_path.exists()


def test_subagent_stop_hook_is_a_silent_noop_when_unarmed(tmp_path, sandbox):
    registry_path = tmp_path / "reg.json"
    env = {"INTERLOCK_OUTSTANDING_REGISTRY_PATH": str(registry_path)}
    # Armed start populates the registry, then an UNARMED stop must leave it untouched.
    run_hook_subprocess("subagent_start.py", sandbox, {"agent_id": "worker-1", "description": "x"}, env=env)
    proc = run_hook_subprocess("subagent_stop.py", sandbox, {"agent_id": "worker-1"}, env=env, armed=False)
    assert proc.returncode == 0, proc.stderr
    entries = json.loads(registry_path.read_text(encoding="utf-8"))
    assert [e["id"] for e in entries] == ["worker-1"], "an unarmed stop must not clear the entry"
