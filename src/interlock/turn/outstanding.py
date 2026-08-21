# SPDX-License-Identifier: Apache-2.0
"""The best-effort, harness-user-level outstanding-agent registry.

`subagent_start.py` writes an entry here when a delegated agent is dispatched;
`subagent_stop.py` removes it when that agent's stop event fires; `user_prompt_submit.py`
reads it to decide whether to remind the operator to run a live probe. All three share the
read/write/prune logic in this module rather than each reimplementing it.

**This registry is not, and cannot be, session-scoped.** A harness's own hook system
generally has no documented way to ask "which subagents did *this* session dispatch," so
this file lives at a fixed, user-level path and is shared by every session running on
this machine. A session that crashes without ever firing its stop event leaves a
permanent entry here unless something prunes it -- which is exactly what the staleness
cutoff in `prune_and_load` does, and exactly why nothing that reads this registry ever
treats it as ground truth. See `docs/INTEGRATION.md` for the disclosed consequences of
this design before you rely on it for anything more than a reminder trigger.

Named `outstanding.py` rather than `registry.py` to avoid colliding with
:mod:`interlock.registry` -- the unified `interlock` CLI's own table of installable gate
and hook identifiers, which is a wholly different thing this module has no relationship
to.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def extract_first_string(payload: dict, keys: tuple) -> str | None:
    """First string value found at any of `keys` in `payload`.

    Defensive by design: a harness's exact hook payload key names are not a contract
    this package controls, and different harnesses (or different versions of the same
    one) have been observed to use different casings for the same field.
    """
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


AGENT_ID_KEYS = ("agent_id", "id", "task_id", "subagent_id", "agentId", "taskId")
DESCRIPTION_KEYS = ("description", "agent_type", "task", "prompt")


def record_start(registry_path: Path, payload: dict) -> None:
    """Add or refresh an entry for a dispatched agent. Never raises."""
    agent_id = extract_first_string(payload, AGENT_ID_KEYS)
    if not agent_id:
        return
    description = extract_first_string(payload, DESCRIPTION_KEYS)
    try:
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        entries = _read_entries(registry_path)
        entries = [e for e in entries if e.get("id") != agent_id]
        entries.append({
            "id": agent_id,
            "description": (description or "(no description)")[:80],
            "started_at": time.time(),
        })
        registry_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    except Exception:
        pass


def record_stop(registry_path: Path, payload: dict) -> None:
    """Remove the entry for a returned agent. Never raises."""
    agent_id = extract_first_string(payload, AGENT_ID_KEYS)
    if not agent_id or not registry_path.is_file():
        return
    try:
        entries = [e for e in _read_entries(registry_path) if e.get("id") != agent_id]
        registry_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    except Exception:
        pass


def prune_and_load(registry_path: Path, stale_seconds: int) -> list[dict]:
    """Return non-stale entries, pruning the file as a side effect. Never raises."""
    entries = _read_entries(registry_path)
    now = time.time()
    fresh = [
        e for e in entries
        if isinstance(e, dict) and (now - e.get("started_at", 0)) < stale_seconds
    ]
    if len(fresh) != len(entries):
        try:
            registry_path.write_text(json.dumps(fresh, indent=2), encoding="utf-8")
        except Exception:
            pass
    return fresh


def _read_entries(registry_path: Path) -> list[dict]:
    if not registry_path.is_file():
        return []
    try:
        entries = json.loads(registry_path.read_text(encoding="utf-8"))
        return entries if isinstance(entries, list) else []
    except Exception:
        return []
