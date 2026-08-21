#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Stop hook: refuse to end a turn in which any assistant message lacked its role label.

WHY THIS EXISTS
---------------
A two-hat convention -- every assistant-authored message opens with a label naming which
hat is speaking -- is easy to state and, in practice, easy to drop silently across a
long, multi-threaded session. The likeliest place for it to drop is a resumption point:
returning from a background-agent notification, returning from a tangent, resuming from a
compaction summary. A convention with no code-level enforcement is exactly the shape most
likely to lapse right there, because nothing forces a re-check at the moment attention
has just been pulled elsewhere.

This hook exists because a self-applied labelling habit is not a control. Correctness
under a purely self-applied rule depends on an agent remembering it, every single
message, forever -- and a long enough session eventually finds the message where that
memory lapses.

WHAT IT CAN AND CANNOT PROVE -- stated narrowly, because overclaiming here would
reproduce the defect it repairs.

It CAN prove: within the turn now ending, some main-thread assistant message carried
user-visible text that did not begin with exactly one valid role label. It checks EVERY
message of the turn, not only the last one -- a lapse is just as likely in an
intermediate message (one carrying a tool call) as in a final one, and a
final-message-only check would miss it.

It CANNOT prove: that the label chosen was the CORRECT hat for the work in that message.
Nothing mechanical can read that. A worker-labelled message doing supervisor-level work
passes this check. It closes "no label" and "blended or malformed label"; it does not
close "wrong label", and must not be described as doing so.

DESIGN BIAS, deliberate. A false positive costs one extra turn. A false negative costs
the violation this exists to stop. Where the two trade off, this errs toward blocking.

The companion `UserPromptSubmit` hook (`user_prompt_submit.py`) cannot do this job: it
runs before the reply exists and can only remind. Reminding is what already failed.

ARMING. A no-op, silently, in a worktree that has not run `interlock arm
turn.role-label` -- see `arming.py`. Checked before anything else in `main()`.
"""
from __future__ import annotations

import json
import re
import sys

from interlock.turn import arming, config

# Ordered longest-first so a label that is a substring of another (an adopter who
# configures overlapping labels) is matched unambiguously.
VALID_LABELS = tuple(sorted({config.SUPERVISOR_LABEL, config.WORKER_LABEL}, key=len, reverse=True))

LABEL_RE = re.compile(r"^\s*\[([^\]\n]{0,80})\]")


def first_visible_text(message_content) -> str:
    """Return the first non-empty user-visible text block of one message.

    Thinking blocks and tool_use blocks are not user-visible prose and carry no label
    obligation. A message that is only tool calls has nothing to check -- returning ""
    for it is what keeps this from blocking on every tool round.
    """
    if isinstance(message_content, str):
        return message_content
    if not isinstance(message_content, list):
        return ""
    for block in message_content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "text":
            continue
        text = block.get("text") or ""
        if text.strip():
            return text
    return ""


def is_real_user_turn(entry: dict) -> bool:
    """True for a genuine user message, False for a tool result.

    Load-bearing. Some harnesses record a tool result as a `type: "user"` entry. A naive
    "walk back to the previous user entry" would stop at the first tool result and
    inspect only the tail of the turn -- exactly the final-message-only check this hook
    exists NOT to be.
    """
    if entry.get("type") != "user":
        return False
    message = entry.get("message")
    if not isinstance(message, dict):
        return True
    content = message.get("content")
    if isinstance(content, str):
        return True
    if not isinstance(content, list):
        return True
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            return False
    return True


def turn_assistant_texts(transcript_path: str):
    """Return every main-thread assistant message text in the turn now ending.

    Sidechain entries are a delegated worker's own transcript and are excluded: a
    worker prefixes its own messages under whatever convention its own dispatch
    established, and its output must never decide whether the supervisor may end its
    turn.

    Never raises. An unreadable transcript means the check cannot be made, and a check
    that cannot be made must not block -- the failure direction here is a hook that
    wedges every turn, which would get it removed.
    """
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except Exception:
        return []

    texts = []
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except Exception:
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("isSidechain"):
            continue
        if is_real_user_turn(entry):
            break
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        text = first_visible_text(message.get("content"))
        if text.strip():
            texts.append(text)
    texts.reverse()
    return texts


def classify(text: str):
    """Return None when the message is correctly labelled, else a reason string."""
    match = LABEL_RE.match(text)
    if not match:
        return "no role label at the start of the message"

    label = "[" + match.group(1) + "]"
    if label not in VALID_LABELS:
        return f"unrecognized role label: {label}"

    # A second bracketed label immediately following the first is a blend: two hats in
    # one message.
    remainder = text[match.end():]
    second = LABEL_RE.match(remainder)
    if second:
        second_label = "[" + second.group(1) + "]"
        if second_label in VALID_LABELS and second_label != label:
            return f"two role labels in one message: {label} and {second_label}"

    return None


def first_message_wrong_channel_failure(texts) -> str | None:
    """The message that answers the operator opens under the SUPERVISOR label. Return a
    reason or None.

    THE REASONING ERROR THIS CATCHES, stated because it is not the obvious one. The
    failure is not forgetting which hat. It is concluding "this turn is hands-on work,
    therefore I am the worker" -- which conflates what the hands are doing with who is
    being addressed. Those are independent. The work can be worker-shaped while the
    message answering the operator is the supervisor's.

    WHY THE FIRST MESSAGE. A turn begins in response to the operator (or to a
    notification they will read); its opening user-visible message is therefore a reply
    to them. Later messages in the same turn are execution narration the operator
    observes rather than a reply they are owed.

    WHAT IT STILL CANNOT PROVE: that a message correctly labelled with the supervisor
    hat is actually doing supervisory work rather than worker-shaped work under a nicer
    label. Nothing mechanical reads that. This closes "the worker hat answered the
    operator", not "the wrong hat did the thinking".
    """
    if not texts:
        return None
    first = texts[0].lstrip()
    if first.startswith(config.SUPERVISOR_LABEL):
        return None
    if first.startswith(config.WORKER_LABEL):
        return (
            f"the first message of this turn answers the operator under "
            f"{config.WORKER_LABEL}, and that channel is reserved to "
            f"{config.SUPERVISOR_LABEL}"
        )
    # Anything else is already caught by classify(); do not double-report it.
    return None


def build_reason(failures) -> str:
    lines = []
    for index, (excerpt, why) in enumerate(failures[:5], 1):
        snippet = " ".join(excerpt.split())[:120]
        lines.append(f"  {index}. {why}\n     starts: {snippet!r}")
    detail = "\n".join(lines)
    plural = "message" if len(failures) == 1 else "messages"
    return (
        f"ROLE LABEL MISSING OR MALFORMED on {len(failures)} assistant {plural} "
        "in this turn:\n\n"
        f"{detail}\n\n"
        "Every assistant-authored message begins with its role label as its FIRST "
        "characters -- interim updates, questions, tool-round narration, decisions, "
        "reports and final responses alike. One message carries exactly one hat; never "
        "blend two.\n\n"
        f"  {config.SUPERVISOR_LABEL}   directs, reviews, answers the operator\n"
        f"  {config.WORKER_LABEL}   authorized hands-on execution\n\n"
        "A missing or wrong label is a role-boundary violation, not a formatting "
        "detail.\n\n"
        "Re-send the affected content with the correct label. Do not argue the label "
        "was implied by an earlier message: the rule is per-message."
    ) + (
        "\n\nThe one above is a CHANNEL violation, not a spelling one. The operator's "
        "only direct interactive channel is with the supervisor hat; the worker hat's "
        "channel is to the supervisor alone. The message that answers the operator is "
        "therefore the supervisor's, however deep in hands-on work the underlying "
        "activity is.\n\n"
        "The error to check for is not 'which hat did I type'. It is the inference "
        "'this turn is hands-on work, therefore I am the worker' -- which conflates "
        "what your hands are doing with who you are addressing. They are independent."
        if any("reserved to" in why for _, why in failures) else ""
    )


def main() -> int:
    if not arming.is_armed("role_label"):
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0

    # Already blocked once this turn. Blocking again would loop.
    if payload.get("stop_hook_active"):
        return 0

    transcript = payload.get("transcript_path")
    if not isinstance(transcript, str) or not transcript:
        return 0

    texts = turn_assistant_texts(transcript)
    failures = []
    for text in texts:
        why = classify(text)
        if why:
            failures.append((text, why))

    # The channel check runs after well-formedness so a message that is BOTH malformed
    # and wrong-channel reports the malformation once, not twice.
    wrong_channel = first_message_wrong_channel_failure(texts)
    if wrong_channel and not any(text is texts[0] for text, _ in failures):
        failures.insert(0, (texts[0], wrong_channel))

    if not failures:
        return 0

    try:
        print(json.dumps({"decision": "block", "reason": build_reason(failures)}))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
