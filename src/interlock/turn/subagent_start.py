#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""SubagentStart hook: record a dispatched background agent in the outstanding registry.

Defensive by design: an unknown or changed hook input schema must never crash or block
the hook chain. On any error, exit 0 silently rather than surface a broken-hook error on
every subagent dispatch. See `outstanding.py` and `config.py` for what this registry is
and its disclosed limits.

**Arming.** A no-op, silently, in a worktree that has not run
`interlock arm turn.subagent-start` (or `interlock install turn.subagent-start`) -- see
`arming.py`'s own docstring for why this now gates every hook in this host, and how that
differs from `interlock.git`'s own installation model.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from interlock.turn import arming, config, outstanding


def main() -> int:
    if not arming.is_armed("subagent_start"):
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    outstanding.record_start(Path(config.OUTSTANDING_REGISTRY_PATH), payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
