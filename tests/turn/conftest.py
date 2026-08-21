# SPDX-License-Identifier: Apache-2.0
"""Fixtures specific to `interlock.turn`'s own test suite: transcript/session-record
builders, and the subprocess runner every hook-level test in this directory drives its
proof through.

`run_hook_subprocess` ARMS the given hook in `cwd` by default before invoking it --
matching how a real adopter would actually rely on one (see `interlock.turn.arming`'s own
docstring: an unarmed hook is a silent no-op by design, exactly like an unarmed git shim).
Every existing test in this directory was written against a package that had no arming
concept at all; auto-arming here is what lets each of those tests keep proving the
predicate it was written to prove without every single one having to spell out an arm
step of its own. Pass `armed=False` to prove the UNARMED case explicitly -- see
`test_arming_gate.py` for the dedicated red/green pair per hook.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "interlock" / "turn"


def write_session_record(root: Path, roster: dict, queue: list, platform: str | None = None,
                          relative_path: str = ".interlock/session_record.json") -> Path:
    document = {"roster": roster, "queue": queue}
    if platform is not None:
        document = {"platforms": [{"platform": platform, "roster": roster, "queue": queue}]}
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def write_transcript(root: Path, entries: list, name: str = "transcript.jsonl") -> Path:
    path = root / name
    with path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")
    return path


def dispatch_entry(agent_id: str, description: str, sidechain: bool = False) -> dict:
    return {
        "type": "user",
        "isSidechain": sidechain,
        "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]},
        "toolUseResult": {
            "isAsync": True,
            "status": "async_launched",
            "agentId": agent_id,
            "description": description,
        },
    }


def notification_entry(task_id: str, status: str = "completed") -> dict:
    return {
        "type": "queue-operation",
        "operation": "enqueue",
        "content": (
            f"<task-notification>\n<task-id>{task_id}</task-id>\n"
            f"<status>{status}</status>\n<summary>done</summary>\n</task-notification>"
        ),
    }


def quiescing_entry(command_name: str) -> dict:
    return {
        "type": "user",
        "isSidechain": False,
        "message": {"role": "user", "content": f"<command-name>/{command_name}</command-name>"},
    }


def run_hook_subprocess(hook_name: str, cwd: Path, payload: dict, env: dict | None = None, armed: bool = True):
    """Run `interlock/turn/<hook_name>` as a real subprocess against `cwd`.

    `hook_name` is the bare filename (e.g. ``"idle_roster.py"``) -- the hook's own module
    stem doubles as its arming key (see `interlock.turn.arming.HOOK_MARKER_NAMES`), which
    is why deriving one from the other below needs no separate lookup table.
    """
    if armed:
        from interlock.turn import arming
        arming.arm(hook_name[: -len(".py")], root=cwd)

    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / hook_name)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=60, cwd=str(cwd),
        env=full_env,
    )
