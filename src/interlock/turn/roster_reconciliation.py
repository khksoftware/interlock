#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Stop hook: compare the hand-written roster against the harness's own record of what
it actually dispatched and what actually reported back.

WHY THIS EXISTS
---------------
A session record's own roster is hand-written by the supervisor. A row reads `running`
because someone typed an entry, and stops reading `running` because someone deleted one.
That is structurally biased toward a false `running` and, symmetrically, toward a
register that has quietly fallen behind a dispatch nobody recorded.

THE DISTINCTION FROM A PROCESS-LIVENESS PROBE -- stated here because a future reader must
not mistake this for one. **This is not a process-liveness probe.** It never asks the
operating system whether a PID is alive, and never acts on that answer. It asks a
narrower, structurally different question: **what does the harness's OWN transcript say
it dispatched, and what does the harness's own transcript say was reported back?** Both
are facts about records the harness itself already wrote, at the moment it wrote them --
not a live re-probe of a running process's current state. A dispatch is a `toolUseResult`
the harness stamps `status: "async_launched"` the instant the tool call returns; a return
is a `<task-notification>` block the harness itself enqueued later. Neither requires
asking anything external whether it is still alive. The failure mode this can have is
therefore different in kind from a liveness probe's: it can be STALE (an old record no
longer describing the present, e.g. after a fresh transcript starts with no history of a
still-running prior dispatch) or INCOMPLETE (a description with no extractable board-item
id), never CONTRADICTORY-BY-DESIGN the way two disagreeing liveness readings are.

Harness shapes this module depends on (verified against a real transcript, not assumed):

1. A dispatch is a fully-structured, main-thread (non-sidechain) fact: the dispatch
   tool's own launch returns synchronously, in the SAME turn, as a `user` entry whose
   top-level `toolUseResult` dict carries `{"isAsync": true, "status": "async_launched",
   "agentId": <harness id>, "description": <free text>}`.
2. A return is NOT a `tool_result`. It never resolves the original dispatch call. It
   arrives later as a separate, top-level `queue-operation` entry (and, redundantly, an
   `attachment` of `type: "queued_command"`) whose `content` is an XML-shaped
   `<task-notification>` block: `<task-id>` (the SAME harness `agentId` from the
   dispatch), `<status>`, `<summary>`, `<result>`.
3. The harness's own dispatch id and the roster's own entry id live in two different,
   unrelated namespaces. The only correlating signal available is the free-text
   `description` string the dispatcher wrote, matched case-insensitively against
   `config.ID_PATTERN` -- a description is written in whatever case its author typed, so
   this match is deliberately case-insensitive even where an adopter's own id convention
   elsewhere in their tooling is case-sensitive.
4. A completion is not necessarily final: the harness's own notification text can state
   that the same task-id may notify more than once (an agent can be resumed and run
   again after its first notification). This module treats "at least one notification
   ever seen for this agentId" as "not outstanding," which means an agent resumed and
   running again after its first notification is MISCLASSIFIED here as returned. This is
   a disclosed, unrepaired blind spot, not an oversight -- see `README.md` /
   `docs/INTEGRATION.md` for the residual.

WHAT IT CAN AND CANNOT PROVE -- stated narrowly on purpose

It CAN prove, from the transcript alone: which harness-assigned dispatches this
session's own main thread made and never saw a notification for ("outstanding"), and
which board-item ids their descriptions named.

It CAN prove, from the roster alone: which ids the roster currently enumerates as live.

It CANNOT prove that a roster entry lacking a matching outstanding dispatch is WRONG --
the dispatch may have happened in an earlier session/transcript this file does not span,
or the description may not have named its id verbatim. This is DIRECTION A below and is
reported, never blocked on, for exactly this reason.

It CAN more safely flag an outstanding dispatch, observed in THIS session's own
transcript, whose extracted id does not appear in the roster at all -- there is no
cross-session ambiguity for a fact this transcript itself just recorded. This is
DIRECTION B (resolved) below, and is the one this hook blocks on.

It CANNOT resolve an outstanding dispatch whose description names no extractable id at
all. That is reported as its own, third bucket (DIRECTION B, unresolved) and is never
folded into either direction's count.

It does NOT catch a supervisor that has correctly, verifiedly registered an EMPTY roster
while dispatchable rows sit queued. That is `idle_roster.py`'s question.

DESIGN BIAS -- deliberately asymmetric. Direction A carries real, structural
false-positive risk (cross-session dispatch history, non-verbatim descriptions) that a
hard refusal would convert into exactly the "false positive trains the operator to
bypass it" failure this whole package is built to avoid. It is therefore reported via the
non-blocking `systemMessage` channel, never `decision: block`. Direction B (resolved) has
no such cross-session ambiguity, so it blocks. Direction B (unresolved) cannot be safely
counted either way and is reported, never blocked on.

ARMING. A no-op, silently, in a worktree that has not run `interlock arm
turn.roster-reconciliation` -- see `arming.py`. Checked before anything else in `main()`.
"""
from __future__ import annotations

import json
import re
import sys

from interlock.turn import arming, config, session_record as sr

_TASK_NOTIFICATION_RE = re.compile(
    r"<task-notification>.*?<task-id>\s*(?P<task_id>[^<\s]+)\s*</task-id>.*?</task-notification>",
    re.DOTALL,
)


def _id_pattern() -> re.Pattern:
    return re.compile(config.ID_PATTERN, re.IGNORECASE)


def extract_ids(text: str) -> frozenset[str]:
    """Board-item ids named anywhere in free text, case-insensitively, upper-cased."""
    if not text:
        return frozenset()
    return frozenset(m.group(0).upper() for m in _id_pattern().finditer(text))


def _notification_candidate_strings(entry: dict) -> list[str]:
    """Every string on this entry that might carry a `<task-notification>` block."""
    out: list[str] = []
    content = entry.get("content")
    if isinstance(content, str):
        out.append(content)
    attachment = entry.get("attachment")
    if isinstance(attachment, dict):
        prompt = attachment.get("prompt")
        if isinstance(prompt, str):
            out.append(prompt)
        acontent = attachment.get("content")
        if isinstance(acontent, list):
            for block in acontent:
                if isinstance(block, str):
                    out.append(block)
    return out


def extract_observed_roster(transcript_path: str | None) -> dict:
    """Walk the WHOLE transcript once. Never raises.

    Returns `{"readable": bool, "dispatched": {agent_id: description},
    "notified": {agent_id, ...}, "outstanding": {agent_id: description}}`.
    """
    empty = {"readable": False, "dispatched": {}, "notified": set(), "outstanding": {}}
    if not transcript_path:
        return empty
    try:
        handle = open(transcript_path, "r", encoding="utf-8", errors="replace")
    except Exception:
        return empty

    dispatched: dict[str, str] = {}
    notified: set[str] = set()
    try:
        with handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(entry, dict):
                    continue
                # A delegated worker's own further dispatches are not this
                # supervisor's roster to answer for.
                if entry.get("isSidechain"):
                    continue

                tool_use_result = entry.get("toolUseResult")
                if isinstance(tool_use_result, dict) and tool_use_result.get("status") == "async_launched":
                    agent_id = tool_use_result.get("agentId")
                    if isinstance(agent_id, str) and agent_id and agent_id not in dispatched:
                        dispatched[agent_id] = str(tool_use_result.get("description") or "")

                for candidate in _notification_candidate_strings(entry):
                    for match in _TASK_NOTIFICATION_RE.finditer(candidate):
                        task_id = match.group("task_id").strip()
                        if task_id:
                            notified.add(task_id)
    except Exception:
        return empty

    outstanding = {aid: desc for aid, desc in dispatched.items() if aid not in notified}
    return {"readable": True, "dispatched": dispatched, "notified": notified, "outstanding": outstanding}


def compare(register_rows, observed_outstanding: dict) -> tuple[tuple[str, ...], tuple, tuple[str, ...]]:
    """Report both directions SEPARATELY -- they are not equally likely and not equally
    dangerous.

    Returns `(direction_a, direction_b_resolved, direction_b_unresolved)`.
      direction_a: roster ids with no matching outstanding dispatch.
      direction_b_resolved: (agent_id, matched_ids) pairs for an outstanding dispatch
        whose description named at least one id, none of which the roster carries.
      direction_b_unresolved: agent_ids of an outstanding dispatch whose description
        named NO extractable id -- reported, never used to decide either direction.
    """
    register_set = set(register_rows)
    ids_by_agent = {agent_id: extract_ids(description) for agent_id, description in observed_outstanding.items()}

    all_observed_ids: set[str] = set()
    for ids in ids_by_agent.values():
        all_observed_ids |= ids

    direction_a = tuple(sorted(row for row in register_set if row not in all_observed_ids))

    direction_b_resolved = []
    direction_b_unresolved = []
    for agent_id, ids in ids_by_agent.items():
        if not ids:
            direction_b_unresolved.append(agent_id)
        elif not (ids & register_set):
            direction_b_resolved.append((agent_id, tuple(sorted(ids))))

    return direction_a, tuple(sorted(direction_b_resolved)), tuple(sorted(direction_b_unresolved))


def build_refuse_reason(direction_b_resolved, direction_a, direction_b_unresolved) -> str:
    lines = [
        "ROSTER MISMATCH -- LIVE DISPATCH WITH NO ROSTER ENTRY.",
        "",
        "This session's own transcript shows a dispatch that has not yet been notified "
        "as stopped, whose description names a board-item id the roster does not "
        "currently enumerate:",
    ]
    for agent_id, ids in direction_b_resolved:
        lines.append(f"  - {agent_id}: named {', '.join(ids)}, not in the roster")
    lines.append("")
    lines.append(
        "Add the entry now, in this turn -- the roster lagging a dispatch is its own "
        "recorded failure, not a detail to fix later."
    )
    if direction_a:
        lines.append("")
        lines.append(
            f"Also reported, not blocking (see the systemMessage channel): "
            f"{len(direction_a)} roster entry(ies) with no matching observed dispatch."
        )
    if direction_b_unresolved:
        lines.append("")
        lines.append(
            f"Also reported, not blocking: {len(direction_b_unresolved)} outstanding "
            f"dispatch(es) whose description named no extractable board-item id."
        )
    return "\n".join(lines)


def build_warn_message(direction_a, direction_b_unresolved) -> str:
    lines = ["ROSTER CHECK -- non-blocking."]
    if direction_a:
        lines.append(
            f"{len(direction_a)} roster entry(ies) claim a live dispatch this transcript "
            f"does not show: {', '.join(direction_a[:8])}"
            + (f", and {len(direction_a) - 8} more" if len(direction_a) > 8 else "") + "."
        )
        lines.append(
            "This is NOT necessarily wrong -- the dispatch may predate this transcript "
            "or its description may not have named the id verbatim. Reported, not "
            "refused, for exactly that reason."
        )
    if direction_b_unresolved:
        lines.append(
            f"{len(direction_b_unresolved)} outstanding dispatch(es) named no "
            f"extractable board-item id in their description, so this check could not "
            f"place them either way: {', '.join(direction_b_unresolved[:8])}"
            + (f", and {len(direction_b_unresolved) - 8} more" if len(direction_b_unresolved) > 8 else "") + "."
        )
    return "\n".join(lines)


def main() -> int:
    if not arming.is_armed("roster_reconciliation"):
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

    transcript_path = payload.get("transcript_path")

    # Defer to a deliberate wind-down, same reasoning as idle_roster.py: a roster
    # mid-correction is expected to disagree with the transcript briefly, and that
    # disagreement is exactly what the wind-down is resolving.
    if sr.a_quiescing_command_is_running(transcript_path, config.QUIESCING_COMMANDS):
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

    state = sr.register_state(node)
    # 'not-observable' means the supervisor already discloses it could not look.
    # Comparing against a state that admits its own blindness manufactures a finding
    # neither side is claiming to have.
    if state == "not-observable":
        return 0
    if state is None:
        return 0

    register_rows = sr.register_ids(node)

    roster = extract_observed_roster(transcript_path)
    if not roster["readable"]:
        return 0

    direction_a, direction_b_resolved, direction_b_unresolved = compare(register_rows, roster["outstanding"])

    if direction_b_resolved:
        try:
            print(json.dumps({
                "decision": "block",
                "reason": build_refuse_reason(direction_b_resolved, direction_a, direction_b_unresolved),
            }))
        except Exception:
            return 0
        return 0

    if direction_a or direction_b_unresolved:
        try:
            print(json.dumps({"systemMessage": build_warn_message(direction_a, direction_b_unresolved)}))
        except Exception:
            return 0
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
