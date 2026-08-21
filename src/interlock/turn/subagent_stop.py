#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""SubagentStop hook: remove a completed background agent from the outstanding registry.

Defensive by design, same rationale as `subagent_start.py`: never crash or block the
hook chain on an unexpected input shape.

**Arming.** A no-op, silently, in a worktree that has not run
`interlock arm turn.subagent-stop` -- see `arming.py`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from interlock.turn import arming, config, outstanding


def main() -> int:
    if not arming.is_armed("subagent_stop"):
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    outstanding.record_stop(Path(config.OUTSTANDING_REGISTRY_PATH), payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
