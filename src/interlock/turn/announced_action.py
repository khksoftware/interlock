#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Stop hook: refuse to end a turn that announced an action without taking it.

WHY THIS EXISTS
---------------
An agent can announce an action in prose ("I'll dispatch the reviewer now") and end its
turn without the tool call that takes it. The cause is not forgetfulness: a stated
intention reads back as settled precisely because it was said out loud, so re-reading
one's own message confirms the intent rather than the act.

This is the same defect class as `role_label.py`: a rule adopted with no mechanism able
to detect its own violation.

WHAT IT CAN AND CANNOT PROVE -- stated narrowly, because overclaiming here would
reproduce the defect it repairs.

It CAN prove: the final assistant message of a turn announced an imminent first-person
repository/system action, and the turn ended without a tool call in that message. By
construction a message carrying a `tool_use` block does not end a turn, so "announced in
the final message" and "announced without acting" are the same condition, and the check
is exact for that condition.

It CANNOT prove: that an action announced *earlier* in a turn, alongside some unrelated
tool call, was actually the action taken. Nothing mechanical can read that
correspondence. This hook closes the final-message shape; it does not close the general
case, and must not be described as doing so.

DESIGN BIAS, and it is deliberate. A false positive costs one extra turn. A false
negative costs the failure this exists to stop. Where the two trade off, this errs
toward blocking -- but every exclusion below exists because a legitimate sentence was
hitting it, not to soften the check.

The companion `UserPromptSubmit` hook cannot do this job: it runs before the reply
exists and can only remind. Reminding is what already failed.

ARMING. A no-op, silently, in a worktree that has not run `interlock arm
turn.announced-action` -- see `arming.py`. Checked before anything else in `main()`.
"""
import json
import re
import sys

from interlock.turn import arming

# --- what an announcement looks like -------------------------------------
#
# First-person imminent-action leads. Periphrastic forms ("the next step is for me
# to...", "I plan to...") are included because the plain forms are the ones an agent
# would naturally vary away from once it knows a check exists, and a detector defeated
# by rephrasing is not a detector.
ANNOUNCEMENT_LEADS = (
    r"\bi'?ll\b",
    r"\bi will\b",
    r"\bi'?m going to\b",
    r"\bi am going to\b",
    r"\bi'?m about to\b",
    r"\bi am about to\b",
    r"\bi shall\b",
    r"\bi plan to\b",
    r"\bi intend to\b",
    r"\blet me\b",
    r"\bfor me to\b",
    r"\bnext,?\s+i\b",
    r"\bnow,?\s+i\b",
    r"\bthen,?\s+i\b",
    r"^\s*going to\b",
    r"^\s*about to\b",
)

# Bare-gerund announcements: "Dispatching the review stream now."
GERUND_LEAD = re.compile(
    r"^\s*(?:now\s+|next,?\s+|then,?\s+)?"
    r"(dispatch|commit|push|writ|creat|build|seal|clos|start|execut|publish|"
    r"generat|regenerat|record|allocat|open|read|check|verif|updat|add|remov|"
    r"fix|run|land|merg|delet|edit|implement|draft|review|audit|measur|test|"
    r"wir|sync|stag|rout|fil|log|apply|proceed|tak|mak|mov|renam|refactor|"
    r"split|fold|queu|dispos|seal)(?:ing|ping|ting|ning|ging)\b",
    re.IGNORECASE,
)

# An announcement lead alone is not enough -- "I'll be brief" is not an action. One of
# these must also appear in the same sentence.
ACTION_VERBS = re.compile(
    r"\b(dispatch|commit|push|write|run|create|build|seal|close|fix|update|"
    r"add|remove|allocate|read|check|verify|execute|publish|generate|"
    r"regenerate|record|open|start|begin|proceed|take|make|apply|route|file|"
    r"log|land|merge|delete|edit|implement|draft|review|audit|measure|test|"
    r"wire|sync|stage|amend|tag|release|configure|set|move|rename|refactor|"
    r"split|fold|queue|disposition|allocate|dispose|handle|address|relay|do)\b",
    re.IGNORECASE,
)

# --- what is NOT an announcement of an action being skipped ---------------
#
# Each of these kills the flag for the sentence it appears in. They are the legitimate
# shapes that would otherwise be blocked forever.
EXCLUSIONS = (
    # Contingent on the operator or on an external event -- correctly not done yet.
    r"\bonce\b",
    r"\bafter you\b",
    r"\bwhen you\b",
    r"\bif you\b",
    r"\bunless you\b",
    r"\bpending your\b",
    r"\bawait",
    r"\byour call\b",
    r"\byour (?:word|go-ahead|go ahead|decision|direction|name|pick)\b",
    r"\bwaiting (?:on|for)\b",
    r"\bbefore (?:you|the operator)\b",
    r"\bon your (?:say|go|instruction|authorization)\b",
    r"\bneeds? your\b",
    r"\bwith your\b",
    # Imperative-conditional forms addressed TO the operator. The contingency is real
    # but carries no "if"/"once", so the patterns above all miss it.
    r"\bsay yes\b",
    r"\bsay the word\b",
    r"\bsay change it\b",
    r"\bapprove\b",
    r"\bauthoriz",
    r"\bwaits? on\b",
    r"\bblocked on\b",
    r"\byours to\b",
    # Reporting and standing by -- not a repository/system action.
    r"\breport back\b",
    r"\blet you know\b",
    # Relaying TO THE OPERATOR is performed by the message itself, so it needs no tool
    # call. Relaying to a delegated worker needs one. The exclusion is therefore keyed
    # on the recipient, not the verb.
    r"\brelay\b[^.]*\bto you\b",
    r"\bstand by\b",
    r"\bnotify you\b",
    r"\bupdate you\b",
    r"\btell you\b",
    r"\bstay on standby\b",
    # Negated -- an explicit statement that something will NOT be done.
    r"\bwon'?t\b",
    r"\bwill not\b",
    r"\bdon'?t\b",
    r"\bdo not\b",
    r"\bnot going to\b",
    r"\bcannot\b",
    r"\bcan'?t\b",
    r"\bhave not\b",
    r"\bhaven'?t\b",
    r"\bdid not\b",
    r"\bdidn'?t\b",
    # Already completed -- past-tense description, not a pending intention.
    r"\balready\b",
    r"\bhas been\b",
    r"\bhave been\b",
    r"\bwas\b",
    r"\bwere\b",
    r"\btook\b",
    r"\bcompleted\b",
    r"\bfinished\b",
    r"\breturned\b",
    r"\bis done\b",
    r"\bran\b",
    r"\bwrote\b",
    r"\bcommitted\b",
    r"\bdispatched\b",
    r"\bpushed\b",
    # Past-tense main verbs in a sentence that OPENS with a gerund. "Splitting it left a
    # head of zero bytes" reports finished work; a naive gerund-lead match alone would
    # wrongly block a report like this.
    r"\bleft\b",
    r"\bproved\b",
    r"\bshowed\b",
    r"\bturned out\b",
    r"\byielded\b",
    r"\bproduced\b",
    r"\blanded\b",
    r"\bcaught\b",
    r"\bstands? at\b",
    # Definitional and stative main verbs. A sentence opening with a gerund and
    # continuing "... means / requires / costs X" DEFINES something; it does not
    # announce it.
    r"\bmeans\b",
    r"\brequires\b",
    r"\binvolves\b",
    r"\bamounts to\b",
    r"\bcosts?\b",
    r"\bis (?:not |merely |exactly |simply )?(?:a|an|the|what|why|how|where)\b",
)

EXCLUSION_RE = re.compile("|".join(EXCLUSIONS), re.IGNORECASE)

# A gerund-initial sentence that also carries a FINITE verb is reporting, not
# announcing: "Splitting it LEFT a head of zero bytes", "Folding the file MEANS moving
# the list", "Writing them EXPOSED a second defect". A bare gerund lead with no finite
# verb -- "Dispatching the reviewer now." -- is the announcement this hook exists to
# catch, and still is.
#
# `\w+ed` alone covers the entire regular past tense; the alternation carries the common
# irregulars and statives. A modal marks irrealis: `would`, `could`, `should`, `might`,
# `may`, and the negated forms describe a hypothetical or an impossibility, never an
# action in progress. An announcement is realis by definition, so a gerund-led sentence
# carrying a modal cannot be one ("Deleting it would destroy that" is a counterfactual
# about a rejected option, the strongest possible signal that no such action is being
# taken).
GERUND_REPORT = re.compile(
    r"^\s*(?:now\s+|next,?\s+|then,?\s+)?\w+ing\b[^.!?]*?\b(?:"
    r"\w+ed|means?|requires?|involves?|costs?|is|are|was|were|has|have|had|"
    r"took|left|caught|showed|proved|found|gave|made|put|kept|held|ran|went|"
    r"gets?|becomes?|remains?|stands?|amounts?|turns? out|buys?|saves?|"
    r"would|could|should|might|may|must|cannot|can't|won't|wouldn't|couldn't"
    r")\b",
    re.IGNORECASE,
)
LEAD_RE = re.compile("|".join(ANNOUNCEMENT_LEADS), re.IGNORECASE | re.MULTILINE)

FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`]*`")
QUOTE_LINE_RE = re.compile(r"^\s*>.*$", re.MULTILINE)


def strip_non_prose(text: str) -> str:
    """Remove content that quotes rather than asserts.

    Load-bearing rather than cosmetic: this rule's own statement, and any example of the
    failure it catches, are things an agent must be able to write about without
    tripping the check. A detector that cannot be discussed without firing gets
    disabled, and a disabled detector is worse than none because its presence implies
    coverage.
    """
    text = FENCE_RE.sub(" ", text)
    text = QUOTE_LINE_RE.sub(" ", text)
    text = INLINE_CODE_RE.sub(" ", text)
    return text


def sentences(text: str):
    """Split prose into sentence-ish units.

    Bullets and line breaks split too: an announcement is routinely its own bullet, and
    joining a bullet list into one unit would let a single exclusion word anywhere in
    the list clear every announcement in it.
    """
    for line in re.split(r"[\r\n]+", text):
        line = line.strip().lstrip("-*+ \t").strip()
        if not line:
            continue
        for part in re.split(r"(?<=[.!?])\s+", line):
            part = part.strip()
            if part:
                yield part


def announced_actions(text: str):
    """Return sentences that announce an imminent, un-taken action."""
    hits = []
    for sentence in sentences(strip_non_prose(text)):
        if sentence.endswith("?"):
            continue
        if EXCLUSION_RE.search(sentence):
            continue
        lead = LEAD_RE.search(sentence)
        if lead:
            if ACTION_VERBS.search(sentence):
                hits.append(sentence)
            continue
        if GERUND_LEAD.match(sentence) and not GERUND_REPORT.match(sentence):
            hits.append(sentence)
    return hits


def final_assistant_text(transcript_path: str) -> str:
    """Return the text of the last main-thread assistant message.

    Sidechain entries are a delegated worker's own transcript and are excluded: a
    worker's message must not decide whether the supervisor may end its turn.

    Never raises. An unreadable transcript means the check cannot be made, and a check
    that cannot be made must not block -- the failure direction here is a hook that
    wedges every turn, which would get it removed.
    """
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except Exception:
        return ""

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
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            continue
        # A message carrying a tool call did not end the turn; if the last assistant
        # entry somehow has one, there is nothing to enforce.
        if any(
            isinstance(block, dict) and block.get("type") == "tool_use"
            for block in content
        ):
            return ""
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def build_reason(hits) -> str:
    quoted = "\n".join(f"  - {h}" for h in hits[:5])
    return (
        "ANNOUNCED BUT NOT TAKEN. This turn is ending with a sentence that announces "
        "an action, and no tool call was made in the message that announced it:\n\n"
        f"{quoted}\n\n"
        "A stated intention reads back as settled precisely because it was said out "
        "loud. The standing rule is: THE TOOL CALL GOES IN THE SAME MESSAGE AS THE "
        "SENTENCE ANNOUNCING IT, OR THE SENTENCE IS NOT WRITTEN.\n\n"
        "Resolve it one of two ways, and do not resolve it by rewording alone unless "
        "the second genuinely applies:\n"
        "  1. Take the action now, in this turn, with the tool call.\n"
        "  2. If the action is genuinely blocked -- it needs the operator's decision, "
        "or it waits on something not yet returned -- say what it waits on, in the "
        "sentence, rather than stating it as something you are about to do."
    )


def main() -> int:
    if not arming.is_armed("announced_action"):
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

    text = final_assistant_text(transcript)
    if not text:
        return 0

    hits = announced_actions(text)
    if not hits:
        return 0

    try:
        print(json.dumps({"decision": "block", "reason": build_reason(hits)}))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
