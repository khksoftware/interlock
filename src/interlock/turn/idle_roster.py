#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Stop hook: refuse to end a turn with dispatchable rows and an empty roster.

WHY THIS EXISTS
---------------
A supervisor delivering a report reads, to itself, like the end of a turn -- so ready
work sitting behind that report feels like the next session's problem when it was
dispatchable the whole time. Re-reading one's own report confirms the report, not the
board. This is the same defect class as `announced_action.py` and `role_label.py`: a
standing obligation ("keep dispatching while there is dispatchable work and idle
capacity") whose only enforcement was an agent remembering it, every turn, forever.

WHAT IT CAN AND CANNOT PROVE, stated narrowly.

It CAN prove: at the moment the turn ended, the session record's own queue held at least
one row whose derived status is `queued`, sequenced, unblocked, and not exempted, while
the same record's roster for this platform is verified-empty.

It CANNOT prove that dispatching is the right call. A row can be genuinely unstartable
for a reason the record has no field for -- which is why an adopter-owned exemption
list exists (`config.SESSION_BOUNDARY_ROWS_PATH`) rather than a predicate trying to guess
the reason. It also cannot see a worker dispatched but not yet registered; that case is
already the register lagging a dispatch, which is its own failure and is not softened
here.

DESIGN BIAS, deliberate: a false positive costs one turn and a sentence saying why
nothing is running. A false negative costs the failure above. Where they trade off this
errs toward blocking.

ARMING. A no-op, silently, in a worktree that has not run `interlock arm
turn.idle-roster` -- see `arming.py`. Checked before anything else in `main()`.
"""
from __future__ import annotations

import json
import sys

from interlock.turn import arming, config, session_record as sr


def build_reason(ready: list[str]) -> str:
    shown = ", ".join(ready[:8])
    more = f", and {len(ready) - 8} more" if len(ready) > 8 else ""
    return (
        "IDLE ROSTER WITH DISPATCHABLE ROWS. This turn is ending with the delegated-"
        f"agent roster declaring a verified-empty state while {len(ready)} queue row(s) "
        f"read `queued` with no declared blocker: {shown}{more}.\n\n"
        "A delivered report reads like the end of a turn, which is exactly why the "
        "ready rows behind it get left.\n\n"
        "Resolve it one of two ways, and rewording the report is not one of them:\n"
        "  1. DISPATCH now, in this turn, and update the roster in the same turn -- the "
        "roster lagging a dispatch is its own recorded failure.\n"
        "  2. If a row genuinely cannot be started, say WHY in the report, per row. If "
        "the reason is a real blocker, put it in that row's `blocked_on` where the "
        "board can see it. If it is a structural exemption, add it to the "
        "session-boundary exemption list with its reason.\n\n"
        "A row waiting on a decision the operator has not given is a blocker worth "
        "stating; \"I wanted to report first\" is not."
    )


def main() -> int:
    if not arming.is_armed("idle_roster"):
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0

    # Already blocked once this turn. Blocking again would loop.
    if payload.get("stop_hook_active"):
        return 0

    # Defer to a deliberate wind-down before reading the board at all. A quiescing
    # command ends with an empty roster BY DESIGN, and blocking one loses the session's
    # state.
    if sr.a_quiescing_command_is_running(payload.get("transcript_path"), config.QUIESCING_COMMANDS):
        return 0

    root = sr.repository_root()
    if root is None:
        return 0

    record_path = config.resolved_session_record_path(root)
    document = sr.load_record(record_path)
    if document is None:
        return 0

    node = sr.platform_node(document)
    if node is None:
        return 0
    if not sr.roster_is_empty(node):
        return 0

    exemptions = config.session_boundary_rows(root)
    ready = sr.dispatchable_rows(node, exemptions)
    if not ready:
        return 0

    try:
        print(json.dumps({"decision": "block", "reason": build_reason(ready)}))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
