#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""UserPromptSubmit hook: inject two standing reminders before every turn.

Concern 1 -- ROLE LABEL (unconditional). A supervisor/worker two-hat convention (see
`role_label.py`) has no mechanical enforcement at the point a reply is *composed* --
a `UserPromptSubmit` hook runs before the reply exists, so it cannot inspect or reject
it, only remind. That is a genuine improvement over nothing but is deliberately NOT a
guarantee; `role_label.py`'s own `Stop`-time check is the actual enforcement.

The reminder escalates at boundaries where a self-applied labelling habit is most likely
to have silently dropped: an explicit resumption command, or a turn taken while
delegated work is outstanding (i.e. plausibly a return from a background-agent
notification).

Concern 2 -- OUTSTANDING BACKGROUND AGENTS (conditional). The registry this reads is
user-level, not session-scoped (see `outstanding.py`'s own docstring for why), so two
mitigations apply, both load-bearing:

1. Entries older than the configured staleness cutoff are dropped before reminding.
2. The reminder text is deliberately phrased as "go verify" rather than "these are
   definitely still running" -- the registry is a trigger for a real, live probe, never
   a substitute for one.

Defensive by design: never crash or block prompt submission on a read/parse error --
exit 0 silently, emitting no additional context, rather than surface a broken-hook error
on every single message.

**Arming.** A no-op, silently, in a worktree that has not run
`interlock arm turn.user-prompt-submit` -- see `arming.py`. Unarmed here means no
reminder is ever injected, not merely a weaker one.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from interlock.turn import arming, config, outstanding

ROLE_LABEL_BASE = (
    f"ROLE LABEL: this message is from the operator, so the reply is the "
    f"{config.SUPERVISOR_LABEL} hat's -- that label as its literal first characters, "
    f"never {config.WORKER_LABEL}. One message carries exactly one hat; never blend "
    f"two.\n"
    "The error this exists to stop is not forgetting which hat. It is the inference "
    "'this turn is hands-on work, therefore I am the worker hat', which conflates what "
    "your hands are doing with who you are addressing -- they are independent. The "
    "supervisor hat is the resting state; the worker hat is entered only by naming the "
    "specific authorized action it covers, and if you cannot name it you are not in it."
)


def role_label_escalated(trigger: str) -> str:
    """Escalated reminder that names the specific boundary that fired it.

    Naming the trigger is load-bearing, not decoration: an escalation whose text is
    identical every time it fires stops discriminating and becomes ambient noise.
    """
    return (
        f"ROLE LABEL -- HIGH-RISK BOUNDARY ({trigger}). This is a boundary where a "
        "self-applied labelling habit is most likely to drop unnoticed. Audit the first "
        "characters of the reply explicitly before sending; do not assume the habit is "
        "still being applied. This message is from the operator, so the reply is "
        f"{config.SUPERVISOR_LABEL} -- never {config.WORKER_LABEL}, whatever the work "
        "consists of. One message carries exactly one hat; never blend two.\n"
        "A resumption OUTPUTS the hat rather than inheriting one: the supervisor hat is "
        "the resting state, and the worker hat is entered only by naming the specific "
        "authorized action it covers."
    )


def read_prompt_text() -> str:
    """Return the submitted prompt, or "" if unavailable. Never raises."""
    try:
        raw = sys.stdin.read()
    except Exception:
        return ""
    # Strip a UTF-8 BOM before parsing -- some shells prepend one when piping, and a
    # leading BOM makes json.loads fail, silently dropping this into the raw-text
    # fallback so every trigger keyed on the prompt's content quietly stops firing.
    raw = raw.lstrip("﻿").strip()
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except Exception:
        return raw
    if isinstance(payload, dict):
        value = payload.get("prompt")
        if isinstance(value, str):
            return value
    return ""


def agent_reminder(fresh: list) -> str:
    if not fresh:
        return ""
    lines = [
        f"{len(fresh)} background agent(s) recorded as dispatched and not yet "
        f"confirmed stopped:"
    ]
    for e in fresh:
        lines.append(f"  - {e.get('id', '?')}: {e.get('description', '(no description)')}")
    lines.append(
        "This registry is best-effort and not session-scoped (entries may be stale or "
        "belong to a different session). Before relying on it: run a live probe now to "
        "get the real, current roster -- do not skip this check just because this list "
        "looks current, and do not treat an empty list here as proof nothing is running "
        "either."
    )
    return "\n".join(lines)


def main() -> int:
    if not arming.is_armed("user_prompt_submit"):
        return 0

    prompt = read_prompt_text()
    fresh = outstanding.prune_and_load(Path(config.OUTSTANDING_REGISTRY_PATH), config.OUTSTANDING_STALE_SECONDS)

    stripped = prompt.lstrip()
    is_resumption = any(stripped.startswith(cmd) for cmd in config.RESUMPTION_COMMANDS)

    if is_resumption:
        header = role_label_escalated("resumption command -- context may have been lost")
    elif fresh:
        header = role_label_escalated(
            "delegated work outstanding -- this turn may be a background-agent return"
        )
    else:
        header = ROLE_LABEL_BASE

    blocks = [header]
    agents = agent_reminder(fresh)
    if agents:
        blocks.append(agents)
    context = "\n\n".join(blocks)

    try:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context[:10000],
            }
        }))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
