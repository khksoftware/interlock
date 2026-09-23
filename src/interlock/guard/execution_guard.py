#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""``PreToolUse``-shaped hook: refuse a command whose shape is a high-confidence, long or
I/O-heavy operation before it runs.

WHY THIS EXISTS
---------------
Some command shapes are reliably expensive before they ever execute -- a recursive scan of
an entire workspace, a full test-suite invocation where one file would answer the question,
an additional git worktree, a database file copied wholesale. A standing instruction to
"prefer the cheaper alternative" is easy to state and easy to override under time pressure,
in the middle of solving a different problem, the same way any purely self-applied rule is.
This hook exists so that class of command is refused mechanically rather than depending on
an agent remembering the instruction every time.

WHAT IT CAN AND CANNOT PROVE -- stated narrowly, because overclaiming here would reproduce
the defect a hook-based control exists to repair.

It CAN prove: the text of a command handed to it through a recognized shell-tool call
matches one of a small, fixed set of high-confidence expensive shapes (see
:func:`classify_command`).

It CANNOT prove that a command NOT matching any shape is actually cheap -- this is a
deliberately small guardrail recognizing only shapes whose broad scope is visible before
execution, not a cost oracle. An ambiguous command that matches nothing here still needs
whatever standing cost-proportionality practice an adopter otherwise follows.

**It CANNOT see anything written through a channel other than a recognized shell-tool
call.** This hook reads a command STRING handed to it by the harness; content written
through a structured file-write tool, an edit tool, or a patch-application tool never
produces a command string for this classifier to read, so this hook is never even invoked
with anything to scan for that channel. **A clean run -- or no invocation at all -- is
therefore not evidence that content written some other way was checked for cost.** This is
a permanent residue class, not a temporary gap: closing it would mean moving the check off
the command string entirely, onto some effect the harness exposes uniformly across every
tool, which is a different and much larger mechanism than this one, of uncertain
reachability on any given harness. See ``README.md``'s "Limits" section.

TWO CHANNELS OF ONE COMMAND STRING: THE COMMAND ITSELF, AND A PAYLOAD IT MAY CARRY.
----------------------------------------------------------------------------------
A shell heredoc or a PowerShell here-string embeds a BODY inside the very string this hook
scans -- and that body is data or prose, not something that is going to execute, MOST of the
time. Scanning the raw string without separating the two means a command that merely WRITES
text mentioning an expensive shape (a note, a patch, a document) is classified identically to
a command that actually RUNS one. :func:`strip_payload_bodies` removes such a body before
classification, leaving the surrounding invocation shape intact.

**This is conditional, not unconditional, and an earlier version of this repair that stripped
unconditionally was itself found to create false negatives, by independent review driving
this hook as a real, armed subprocess.** A heredoc body fed to a shell (`bash <<'EOF' … EOF`,
or a heredoc piped into one) IS the command, not data -- stripping it hid a genuinely
expensive one. A heredoc with no confirmed terminator is not evidence of a real heredoc at
all -- treating it as one and stripping to end-of-input let a stray `<<` in ordinary prose
silently discard a genuinely expensive command sitting on a later line. And a `<<` sitting
inside a quoted string -- whether that string opens and closes on one line, or opens on one
line and does not close until a later one, and whether or not a quote character in it is
backslash-escaped -- is not a heredoc redirect at all in any shell: a match on the two
characters alone, without tracking quoting correctly, let ordinary prose that happened to
contain both `<<` and a later matching bare word (`echo "a << ZZZ"` followed by a real
command and a coincidental `ZZZ` line, on one line or split across several) silently discard
the real command sitting between them. All four are closed in :func:`_strip_heredoc_bodies`:
a body is stripped only when the opening `<<` is confirmed to sit outside any quoted text --
tracked across lines and aware of backslash-escaped quotes, not just within the one line the
`<<` appears on -- a real terminator is found, AND the opening line does not feed the body to
a shell interpreter. **A command whose own text (outside any body this function is confident
is inert data) matches a shape below is refused** -- see that function's own docstring for
exactly which conditions have to hold before anything is stripped, and `README.md`'s Limits
section for the residuals this still discloses rather than closes (a finite, named list of
recognized interpreter names, and a character-level approximation of shell quoting rather
than a full grammar parser).

A blocked command can run only after explicit, disclosed authorization is recorded as an
expiring, one-shot receipt bound to the command's exact SHA-256 -- see
:func:`record_approval`. The approval is bound to the ORIGINAL, unstripped command text;
only classification reads the payload-stripped copy.

ARMING. A silent no-op in a worktree that has not run `interlock arm guard.execution-guard`
-- see :mod:`interlock.guard.arming`. Checked before anything else in :func:`main`.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import sys
import time
import uuid
import warnings
from typing import Mapping

from interlock.guard import arming, config

SCHEMA = "interlock-guard-command-cost-approval/1.0"

#: What :func:`record_approval` writes into ``approved_under``, and what
#: :func:`consume_approval` requires to find there.
#:
#: **This is a cited rule, never a claim about who approved.** The field it replaced,
#: ``approved_by: "explicit-user-authorization"``, read as an attestation that a person
#: authorised the command -- and it was never that. This guard has no channel to the user
#: that the calling agent does not also control: the same process just refused can invoke
#: the approval path itself, supply any text it likes for the reason, the alternatives and
#: the baseline plan, and the record is written and later accepted with no differently-
#: privileged party involved at any point. The single use, the SHA-256 binding and the
#: expiry are real and are not in question; only the claim the old field's NAME made was
#: false. So the field answers *which rule licenses this record's existence*, never *who
#: approved it*.
#:
#: The value is kept identical to the host hook's own label deliberately: the two copies
#: of this guard are compared against each other by contract, and a rename that reached
#: only one of them is the defect this change repairs.
APPROVAL_RULE_LABEL = "rule: explicit user authorization required before recording"

#: Tool names whose ``command``/``cmd``/``source``/``script`` input field is a shell
#: command string this hook can meaningfully scan. A payload under any other tool name
#: never reaches :func:`classify_command` at all -- see the module docstring's residue
#: class.
SHELL_TOOL_NAMES = {
    "bash", "cmd", "command_prompt", "commandprompt", "shell", "powershell",
    "exec", "exec_command", "functions.exec", "functions.exec_command", "computer",
    "computer_use",
}


def command_sha256(command: str) -> str:
    return hashlib.sha256(command.strip().encode("utf-8")).hexdigest().upper()


def _dict(payload: Mapping[str, object], *keys: str) -> Mapping[str, object]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def extract_command(payload: Mapping[str, object]) -> str | None:
    tool_name = next(
        (payload.get(key) for key in ("tool_name", "toolName", "tool", "name")
         if isinstance(payload.get(key), str)),
        None,
    )
    tool_input = _dict(payload, "tool_input", "toolInput", "input", "parameters")
    for key in ("command", "cmd", "source", "script"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            if tool_name is None or str(tool_name).lower() in SHELL_TOOL_NAMES:
                return value
    return None


#: Opens a bash heredoc: ``<<EOF``, ``<<-EOF``, ``<<'EOF'``, ``<<"EOF"``, etc.
_HEREDOC_START_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

#: Opens a PowerShell here-string: ``@'`` or ``@"`` as the last thing on a line. The closing
#: delimiter (``'@`` / ``"@``) must be the first thing on its own line, per PowerShell syntax.
_POWERSHELL_HERESTRING_START_RE = re.compile(r"@(['\"])\s*$")

#: Interpreter/shell names whose presence on a heredoc's or here-string's OPENING line means
#: the body that follows is not data -- it is itself a command about to be executed by that
#: interpreter, directly (``bash <<'EOF'``) or via a pipe into it (``cat <<'EOF' | bash``).
#: Matched as a bare word, after stripping any leading path and any trailing ``.exe``. This
#: list is necessarily finite: an interpreter invoked under a name not on it (an obscure
#: shell, an alias, a wrapper script) is not recognized, and its heredoc body is then treated
#: as data and stripped -- a residual disclosed here and in ``README.md``, not silently
#: assumed away.
_SHELL_CONSUMER_NAMES = {
    "sh", "bash", "zsh", "ksh", "dash", "ash",
    "pwsh", "powershell",
    "cmd",
    "iex",
}


def _opening_line_feeds_an_interpreter(line: str) -> bool:
    """Whether ``line`` -- the line that OPENS a heredoc or here-string -- names or pipes
    into a shell/interpreter, so the body that follows is the command that interpreter is
    about to run, not inert data.

    Deliberately over-broad rather than under-broad: a false match here only leaves inert
    data visible to the classifier (at most a false positive), never the reverse. Checked
    against the OPENING line only, never the body -- this stays a cheap, local check, the
    same shape as every other rule in this module.
    """
    tokens = re.findall(r"[A-Za-z0-9_./\\-]+", line)
    for token in tokens:
        name = token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        if name.endswith(".exe"):
            name = name[: -len(".exe")]
        if name in _SHELL_CONSUMER_NAMES:
            return True
    return False


def _unescaped_double_quote_count(text: str) -> int:
    """Count the ``"`` characters in ``text`` that are real shell quote delimiters, as
    opposed to a backslash-escaped ``\\"`` -- a literal double-quote character INSIDE an
    already-open double-quoted string, per bash's own escaping rule, which does not close
    it. A quote preceded by an EVEN number of consecutive backslashes (including zero) is a
    real delimiter; an ODD number means the last of those backslashes escapes the quote
    itself. Single quotes get no equivalent treatment, deliberately: bash gives backslash no
    special meaning inside a single-quoted string at all (there is no way to escape a ``'``
    there), so every ``'`` is always a real delimiter and a plain count is already correct.

    Found by independent review, alongside the cross-line carry this function's caller now
    tracks: with a naive ``str.count('\"')``, ``echo "she said \\" and a << ZZZ"`` reads as
    an EVEN two quotes before the ``<<`` (both the opener and the escaped one counted alike)
    and so as *outside* quotes, when the string the escaped quote sits inside is still open.
    """
    count = 0
    index = 0
    length = len(text)
    while index < length:
        if text[index] == '"':
            backslashes = 0
            look = index - 1
            while look >= 0 and text[look] == "\\":
                backslashes += 1
                look -= 1
            if backslashes % 2 == 0:
                count += 1
        index += 1
    return count


def _heredoc_operator_is_real(
    line: str, start: int, *, carry_double: bool, carry_single: bool
) -> bool:
    """Whether the ``<<`` opener found at character offset ``start`` in ``line`` is an
    actual shell heredoc redirect, as opposed to plain text that merely CONTAINS the two
    characters ``<<`` inside a quoted string -- possibly one whose quoting started on an
    EARLIER line.

    ``echo "a << ZZZ"`` never opens a heredoc anywhere -- the redirect operator is only
    special outside of quotes, and here it sits inside a complete, self-closing
    double-quoted string. Found by independent review: with no such check, the regex below
    matches the `<<` and the following bare word regardless of quoting, a later line that
    happens to spell that same bare word is then read as a genuine terminator, and
    everything between -- a real command, not a heredoc body -- is silently stripped.

    Approximated the same cheap, local way every other check in this module works: an even
    count of ``"`` and an even count of ``'`` before ``start`` -- XORed against
    ``carry_double``/``carry_single``, the quote state :func:`_strip_heredoc_bodies` carries
    in from every PRIOR line -- means neither quote type is open at that point, so the
    operator sits outside any string and is a real redirect. The ``"`` count is
    backslash-escape-aware (:func:`_unescaped_double_quote_count`); the ``'`` count is not,
    because bash gives backslash no escaping power inside a single-quoted string.

    **Two shapes independent review found this used to misread, both now closed**, because a
    double-quoted string spans lines in real shell syntax and a backslash can escape a quote
    character without ending the string: a ``<<`` sitting inside a quoted string that STARTED
    on an earlier line (the incoming carry state was previously always assumed closed,
    reading a still-open multi-line string as closed); and a backslash-escaped quote ahead of
    a ``<<`` on the SAME line (a naive count read the escaped quote as a second real
    delimiter, closing what was actually still an open string). Both are character-level
    shell-quoting approximations, not a full shell-grammar parser -- a construct that reopens
    or changes quoting context through shell expansion (command substitution, ANSI-C
    ``$'...'`` quoting, backtick substitution) is not modeled and is not claimed to be.

    **Biased toward the safe direction when this cannot tell**, the same bias every check in
    this module applies: an odd quote count reads as "inside quotes, not a real heredoc"
    rather than the reverse, so the failure mode of this heuristic being wrong is a genuine
    heredoc left un-stripped (its body stays visible to the classifier -- at most a false
    positive) rather than ordinary quoted prose being mistaken for one (which is the
    direction that silently drops a real command). A line whose own quoting this parity
    check misreads -- an apostrophe in ordinary prose ahead of a genuine heredoc opener on
    the same line, for instance -- lands on that same safe side: the body stays visible
    rather than being stripped.
    """
    before = line[:start]
    inside_double = carry_double != (_unescaped_double_quote_count(before) % 2 == 1)
    inside_single = carry_single != (before.count("'") % 2 == 1)
    return not inside_double and not inside_single


def _find_real_heredoc_start(
    line: str, *, carry_double: bool, carry_single: bool
) -> re.Match[str] | None:
    """The first :data:`_HEREDOC_START_RE` match on ``line`` that is an actual heredoc
    redirect rather than a coincidental ``<<`` sitting inside quoted text -- see
    :func:`_heredoc_operator_is_real`. ``carry_double``/``carry_single`` is the quote state
    :func:`_strip_heredoc_bodies` carries in from every prior line, so a quoted string that
    opened on an earlier line and has not yet closed is still recognized here. Returns
    ``None`` when every candidate match on the line is inside quotes, exactly as if no
    heredoc opener were present on it at all."""
    for candidate in _HEREDOC_START_RE.finditer(line):
        if _heredoc_operator_is_real(
            line, candidate.start(), carry_double=carry_double, carry_single=carry_single
        ):
            return candidate
    return None


def _strip_heredoc_bodies(command: str) -> str:
    """Remove a bash heredoc BODY from ``command`` -- but only when it is safe to: the
    opening ``<<`` is confirmed to sit outside any quoted text, a real terminator was found,
    AND the opening line does not feed the body to an interpreter. Keeps the invocation line
    (``cmd <<EOF``) intact either way, so the classifier still sees the shape of the command
    itself.

    **Four false-negative classes an earlier version of this function had, all found by
    independent review driving this hook as a real, armed subprocess, and all closed here.**

    1. **A heredoc body fed to a shell IS the command, not data.** ``bash <<'EOF' … EOF``
       and ``cat <<'EOF' | bash … EOF`` both execute their body. Unconditional stripping hid
       a genuinely expensive command inside its own payload -- see
       :func:`_opening_line_feeds_an_interpreter`, which this function now checks before
       dropping anything.
    2. **A missing terminator is not evidence of a real heredoc.** The previous version
       stripped from the opener to end-of-input whenever no terminator line ever matched, so
       a stray ``<<`` in ordinary prose (``echo "shift the value << two places"``, with no
       later line spelling ``two``) silently discarded every following line -- including a
       genuinely expensive command sitting on its own line right after it. A terminator that
       is never found now means the lines are restored UNCHANGED rather than discarded: the
       safe reading of "this did not look like a real, complete heredoc" is to leave
       everything in, not to erase it.
    3. **A spurious match WITH a terminator present is not a real heredoc either.** ``<<``
       is not a redirect operator inside a quoted string in any shell -- ``echo "a << ZZZ"``
       followed by a real command and then a bare ``ZZZ`` line executes all three lines, none
       of them a heredoc. An earlier repair matched the opener regardless of quoting and
       stripped the real command sitting between the two coincidental lines. See
       :func:`_heredoc_operator_is_real`, which this function now checks before treating any
       match as a genuine heredoc opener at all.
    4. **A quoted string does not have to close on the line it opened, and a quote character
       can be escaped without closing its string.** The check added for (3) originally reset
       to "outside any quote" at the start of every line and counted every ``"`` alike. Two
       shapes defeated that, both found by a further independent review pass: a double-quoted
       string that OPENS on one line and does not close until a later one (the ``<<`` on the
       line in between read as outside quotes, because the carried state reset every line
       instead of tracking the still-open string); and a backslash-escaped ``\"`` ahead of a
       genuine ``<<`` on one line (counted as a second real quote, making the parity look
       closed when the string was still open). :func:`_heredoc_operator_is_real` now takes
       the running quote state THIS function carries across lines, and counts ``"`` in an
       escape-aware way (:func:`_unescaped_double_quote_count`); both shapes now read as
       "still inside a quote," the same safe reading (3) already established.

    **For a cost guard the safe direction is the opposite of what an earlier version of this
    function's own comment said.** Leaving a real payload body in the classified text costs
    at most a false positive, caught by the standing cost-proportional practice the guard
    exists alongside; removing text that was actually going to execute silently disarms the
    guard. All four repairs above bias toward NOT stripping whenever this function cannot
    confirm the body is inert.
    """
    lines = command.split("\n")
    output: list[str] = []
    index = 0
    # Quote state carried forward across lines -- whether an unterminated double- or
    # single-quoted string is still open entering the NEXT line. Only ever updated from a
    # line's own full text, never from a heredoc/here-string BODY: body content is literal
    # payload data, not shell syntax, and does not affect the outer command's quoting.
    carry_double = False
    carry_single = False
    while index < len(lines):
        line = lines[index]
        match = _find_real_heredoc_start(
            line, carry_double=carry_double, carry_single=carry_single
        )
        output.append(line)
        carry_double = carry_double != (_unescaped_double_quote_count(line) % 2 == 1)
        carry_single = carry_single != (line.count("'") % 2 == 1)
        if not match:
            index += 1
            continue
        tag = match.group(2)
        body_start = index + 1
        terminator = re.compile(rf"^[ \t]*{re.escape(tag)}[ \t]*$")
        cursor = body_start
        while cursor < len(lines) and not terminator.match(lines[cursor]):
            cursor += 1
        if cursor >= len(lines):
            # No terminator anywhere in the rest of the command: this was not a real,
            # complete heredoc. Restore every remaining line unchanged and stop -- there is
            # nothing left to scan for a further heredoc after this.
            output.extend(lines[body_start:])
            return "\n".join(output)
        if _opening_line_feeds_an_interpreter(line):
            # The body is the command a shell is about to run -- keep it visible.
            output.extend(lines[body_start:cursor])
        index = cursor + 1  # consume the terminator line itself
    return "\n".join(output)


def _strip_powershell_herestring_bodies(command: str) -> str:
    """Remove a PowerShell here-string BODY from ``command`` -- two of
    :func:`_strip_heredoc_bodies`'s three conditions, for the identical reasons: a missing
    closing delimiter restores the lines unchanged rather than discarding to end-of-input,
    and a body fed to an interpreter (``Invoke-Expression``/``iex`` on the opening line) is
    kept visible rather than stripped. See that function's docstring for the full reasoning;
    this is the one-shape-down application of it. The third condition (the opener confirmed
    to sit outside quoted text) has no here-string equivalent to apply: the opening regex
    already requires ``@'``/``@"`` to be the last thing on the line, so a quoted string that
    merely contains those two characters followed by more text never matches it at all.

    Narrower than the bash case in one way, disclosed rather than assumed away: a
    here-string is ordinarily assigned to a variable and invoked LATER, on a different line
    (``$x = @'…'@`` then ``Invoke-Expression $x``) -- this function only recognizes an
    interpreter named on the SAME line as the opening ``@'``/``@"``, which the bash case
    does not need to worry about (a heredoc's consumer is always on its own opening line).
    """
    lines = command.split("\n")
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = _POWERSHELL_HERESTRING_START_RE.search(line)
        if not match:
            output.append(line)
            index += 1
            continue
        quote = match.group(1)
        output.append(line)
        body_start = index + 1
        terminator = re.compile(rf"^{re.escape(quote)}@")
        cursor = body_start
        while cursor < len(lines) and not terminator.match(lines[cursor]):
            cursor += 1
        if cursor >= len(lines):
            output.extend(lines[body_start:])
            return "\n".join(output)
        if _opening_line_feeds_an_interpreter(line):
            output.extend(lines[body_start:cursor])
        index = cursor + 1  # consume the terminator line itself
    return "\n".join(output)


def strip_payload_bodies(command: str) -> str:
    """Remove a heredoc's or here-string's BODY from ``command`` before classification --
    but only when doing so cannot hide a command that will actually execute.

    See :func:`_strip_heredoc_bodies` for the conditions that make stripping unsafe (a body
    fed to a shell interpreter; a heredoc with no confirmed terminator; a ``<<`` that never
    sat outside quoted text in the first place) and why, for a cost guard, the safe default
    is to leave text IN rather than strip it out. This
    function's own recognized-interpreter list is finite (see ``_SHELL_CONSUMER_NAMES``);
    an interpreter invoked under an unrecognized name is not detected as a shell consumer,
    and its heredoc body is then treated as data.

    Hashing and approval always use the ORIGINAL, unstripped command (see :func:`run_hook`)
    -- only classification reads this (conditionally) stripped copy, so an approval receipt
    still binds to the exact real command a user authorized.
    """
    return _strip_powershell_herestring_bodies(_strip_heredoc_bodies(command))


def classify_command(command: str) -> tuple[dict[str, str], ...]:
    text = command.strip()
    lowered = text.lower().replace("\\", "/")
    findings: list[dict[str, str]] = []

    def add(rule_id: str, activity: str, alternative: str) -> None:
        findings.append({"rule_id": rule_id, "activity": activity, "alternative": alternative})

    if re.search(r"\bgit(?:\s+-\S+)*\s+worktree\s+add\b", lowered):
        add(
            "COST-WORKTREE-ADD",
            "creation of an additional Git worktree",
            "reuse an existing isolated worktree or prove why a new checkout is required",
        )

    broad_workspace_rg = bool(
        re.search(r"\brg(?:\.exe)?\b[^\n]*\sworkspace(?:\s|$|--glob)", lowered)
        and not re.search(r"workspace/[^\s'\"]+\.[a-z0-9]{1,8}(?:[\s'\"]|$)", lowered)
    )
    recursive_tree = bool(
        ("get-childitem" in lowered and "-recurse" in lowered and (
            " workspace" in lowered or " -path ." in lowered or " -literalpath ." in lowered
        ))
        or re.search(r"\bgrep\s+-(?:[^\s]*r[^\s]*)\s+[^\n]*(?:\s\.|\sworkspace)(?:\s|$)", lowered)
        or re.search(r"\bfind\s+(?:\.|workspace)(?:\s|$)", lowered)
        or re.search(r"(?:^|[&|]\s*)dir\s+/s(?:\s+\.|\s+workspace)?(?:\s|$)", lowered)
        or re.search(r"(?:^|[&|]\s*)for\s+/r(?:\s+\.|\s+workspace)?(?:\s|$)", lowered)
        or re.search(r"(?:^|[&|]\s*)where\s+/r\s+(?:\.|workspace)(?:\s|$)", lowered)
    )
    if broad_workspace_rg or recursive_tree:
        add(
            "COST-FULL-TREE-SCAN",
            "a broad recursive repository/workspace scan",
            "query exact known files, indexed database rows, or the smallest relevant subtree",
        )

    if ("pytest" in lowered and _has_directory_test_target(text)) or re.search(
        r"\b(?:python(?:\.exe)?\s+)?tooling/run_tests\.py\b", lowered
    ):
        add(
            "COST-FULL-TEST-SUITE",
            "a full test directory or framework suite",
            "run the change-triggered planner and its affected modules or parameter cells",
        )
    explicit_test_modules = re.findall(r"tests/[^\s'\"]+\.py", lowered)
    if len(set(explicit_test_modules)) > 20:
        add(
            "COST-BROAD-TEST-CLOSURE",
            f"an explicit closure of {len(set(explicit_test_modules))} test modules",
            "reuse accepted evidence or justify why the complete closure is reachable",
        )

    copy_tool = re.search(r"\b(?:copy-item|copy|cp|robocopy|xcopy)\b", lowered)
    database_operand = re.search(r"\.(?:sqlite3?|db)(?:[\s'\"]|$)", lowered)
    if copy_tool and database_operand:
        add(
            "COST-DATABASE-COPY",
            "a database copy",
            "use a read-only query, existing snapshot, or smallest identity-preserving fixture",
        )

    if "get-filehash" in lowered and "get-childitem" in lowered and "-recurse" in lowered:
        add(
            "COST-RECURSIVE-HASH",
            "recursive hashing of a file tree",
            "hash only declared changed or authority-bearing files",
        )

    return tuple(findings)


def _has_directory_test_target(command: str) -> bool:
    normalized = command.replace("\\", "/")
    return bool(re.search(r"(?<![\w./-])tests(?:[\s'\"]|$)", normalized, re.IGNORECASE))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


# --- shared-target atomic replace -------------------------------------------------------
#
# Self-contained on purpose. This distribution declares no dependencies, and this hook is
# invoked by an adopter's harness as a subprocess at a ``PreToolUse``-shaped boundary, so
# everything it needs at import time is either the standard library or this package's own
# source. Nothing below imports anything outside it, and nothing below is reachable only
# through a host subpackage.
#
# The hazard: on Windows, ``os.replace`` onto a target another process holds open -- EVEN
# FOR READ -- is refused with ``PermissionError`` whose ``winerror`` is 5. The refusal is
# transient and unrelated to the content of either file, so an approval receipt written
# while a concurrent invocation happens to be reading it back fails for a reason that has
# nothing to do with the write being attempted. :func:`record_approval` writes exactly such
# a target and :func:`consume_approval` is exactly such a reader. On every other platform
# ``winerror`` does not exist, the retry below re-raises on the first refusal, and this
# helper is a faithful pass-through that claims nothing.
# ----------------------------------------------------------------------------------------


REPLACE_MAX_ATTEMPTS = 6
REPLACE_BACKOFF_SECONDS = 0.05


class ReplaceNotApplied(PermissionError):
    """`replace_with_retry_verified` exhausted its retries and confirmed, by reading
    `target` back, that it does NOT carry the bytes `source` held: the replace genuinely
    did not apply. A `PermissionError` subclass, so the `except OSError` idiom an atomic
    writer's caller already uses catches it unchanged."""


class ReplaceVerificationError(OSError):
    """`replace_with_retry_verified` exhausted its retries, and reading `target` back to
    tell whether the replace actually landed ITSELF failed: whether the write applied is
    genuinely unknown and needs a manual check.

    **An `OSError` subclass, and that is not cosmetic.** A sibling implementation of this
    helper once derived this class from `RuntimeError` while `ReplaceNotApplied` derived
    from `PermissionError`; the asymmetry meant a caller writing `except OSError` -- the
    ordinary idiom around an atomic write -- handled one outcome of one function and let
    the other escape unwrapped, past its own error contract. Two outcomes of one call must
    share one base. A caller that still wants to special-case "this needs a manual check"
    catches this class explicitly BEFORE a broader `except OSError`."""


class ReplaceVerificationSkipped(RuntimeWarning):
    """`replace_with_retry_verified` could not read `source` before attempting the
    replace, so it has no bytes to compare `target` against afterward -- verification
    is impossible, not merely inconclusive.

    The replace is still attempted rather than refused: `os.replace` does not need the
    same access `open()` for read does, and a real lock reproduces exactly this split --
    a source opened with share flags that deny read but still permit rename (measured
    on this platform: `open(source, "rb")` raises `PermissionError` while
    `os.replace(source, target)` succeeds outright). Refusing here would turn a call
    that works today into a hard failure for no corresponding safety gain.

    But the function's entire contract is verification, and none can happen once
    `source` is unreadable, so silently returning exactly as a verified success would
    is its own defect (`ENG-00736`). This warning is the signal available in its
    place: a `PreToolUse` hook may depend on no logger and may import nothing beyond
    the standard library, and `warnings.warn` is part of it. By default Python prints
    an unhandled warning once to stderr; a caller that wants to notice
    programmatically wraps the call in `warnings.catch_warnings(record=True)`."""


def replace_with_retry(source, target) -> None:
    """`os.replace`, retrying only the transient refusal of a rename onto a target another
    process holds open.

    On Windows that refusal is `PermissionError` with `winerror == 5`, raised even when the
    holder opened the target for READ only; it is unrelated to the content of either file
    and is never by itself evidence of a torn state. `winerror` does not exist on other
    platforms, so `getattr(error, "winerror", None) != 5` re-raises immediately there and
    this function is a faithful pass-through -- it adds a Windows-specific retry and claims
    nothing anywhere else."""
    attempt = 0
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError as error:
            attempt += 1
            if getattr(error, "winerror", None) != 5 or attempt >= REPLACE_MAX_ATTEMPTS:
                raise
            time.sleep(REPLACE_BACKOFF_SECONDS * attempt)


def replace_with_retry_verified(source, target) -> None:
    """`replace_with_retry`, plus the classification a bare refusal cannot give.

    When the retries are exhausted, a raised `PermissionError` on its own cannot
    distinguish "genuinely did not apply" from "applied despite the raise" from "unknown,
    because checking which of those two is true itself failed." The third is a real state
    and the second has been observed for real: a write whose caller saw a traceback and a
    non-zero exit for an operation that had in fact completed, and re-ran it.

    `source`'s own on-disk bytes are read BEFORE the replace is attempted -- the literal
    bytes that land on `target` if it succeeds -- so verification never depends on the
    caller re-deriving what it wrote from its own text, JSON, encoding or newline choices.

    - Success, immediately or after a retry: returns normally. Unchanged from a bare
      `os.replace` for the overwhelming majority of calls.
    - Retries exhausted, and `target` now holds exactly what `source` held: the replace did
      land despite the raised error. Returns normally rather than raising.
    - Retries exhausted, and `target`'s bytes differ: raises `ReplaceNotApplied`.
    - Retries exhausted, and reading `target` back itself raises: raises
      `ReplaceVerificationError`.
    - Anything else `replace_with_retry` lets through propagates unchanged. This function
      interposes only on the one refusal `replace_with_retry` itself retries and can
      exhaust.

    Accepts `str` or any `os.PathLike` for both operands, and reads through `open()` rather
    than a `pathlib` method, so it imposes no import of its own beyond `os`, `time` and
    `warnings` -- all three standard library ("`replace_with_retry_verified` could not
    read `source`" is signalled with a `ReplaceVerificationSkipped` warning rather than
    silently degrading; see that class's docstring)."""
    try:
        with open(source, "rb") as handle:
            intended = handle.read()
    except OSError as read_error:
        # `source` is not readable before a replace was even attempted -- not a case this
        # function's verification should interpret, and not evidence the replace itself is
        # in trouble: `os.replace` does not require read access to `source`, measured
        # against a real lock that denies one and not the other (`ENG-00736`). Let the
        # replace raise whatever `os.replace` itself raises rather than mask it with a
        # verification error about a replace that was never reached -- but say so LOUDLY
        # first: this function's whole contract is verification, none can happen here, and
        # returning silently would be indistinguishable from a verified success.
        warnings.warn(
            f"replace_with_retry_verified: {source} could not be read before replacing "
            f"{target} ({read_error}); proceeding WITHOUT verification.",
            ReplaceVerificationSkipped,
            stacklevel=2,
        )
        replace_with_retry(source, target)
        return
    try:
        replace_with_retry(source, target)
        return
    except PermissionError as error:
        if getattr(error, "winerror", None) != 5:
            raise
        try:
            with open(target, "rb") as handle:
                current = handle.read()
        except OSError as read_error:
            raise ReplaceVerificationError(
                f"os.replace of {source} onto {target} was refused after "
                f"{REPLACE_MAX_ATTEMPTS} attempts, and reading {target} back to tell "
                f"whether the replace actually landed itself failed: {read_error}. "
                f"Whether this write applied is unknown; it needs a manual check."
            ) from read_error
        if current == intended:
            return
        raise ReplaceNotApplied(
            f"os.replace of {source} onto {target} was refused after "
            f"{REPLACE_MAX_ATTEMPTS} attempts, and read-back confirms {target} does not "
            f"carry the bytes {source} held -- the replace did not apply."
        ) from error


def _atomic_json(path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    replace_with_retry_verified(temporary, path)


def record_approval(
    sha256: str,
    *,
    reason: str,
    alternatives: str,
    baseline_plan: str,
    expires_minutes: int | None = None,
):
    if not re.fullmatch(r"[0-9A-Fa-f]{64}", sha256):
        raise ValueError("command SHA-256 must contain exactly 64 hexadecimal characters")
    minutes = expires_minutes if expires_minutes is not None else config.default_approval_expiry_minutes()
    if minutes < 1 or minutes > 1440:
        raise ValueError("expiry must be between 1 and 1440 minutes")
    now = _utc_now()
    payload = {
        "schema": SCHEMA,
        "command_sha256": sha256.upper(),
        # NOT A CLAIM ABOUT WHO APPROVED. This guard has no channel to the user that the
        # calling agent does not also control, so this field records the RULE the record
        # is written under, never a verified fact. The single use, the SHA binding and the
        # expiry below are real; the authorization is asserted, not verified. See
        # :data:`APPROVAL_RULE_LABEL` for the full account.
        "approved_under": APPROVAL_RULE_LABEL,
        "reason": reason.strip(),
        "alternatives_considered": alternatives.strip(),
        "baseline_reuse_plan": baseline_plan.strip(),
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z"),
        "uses_remaining": 1,
    }
    if not all(payload[key] for key in ("reason", "alternatives_considered", "baseline_reuse_plan")):
        raise ValueError("reason, alternatives, and baseline plan must be non-empty")
    path = config.state_root() / "approvals" / f"{sha256.upper()}.json"
    _atomic_json(path, payload)
    return path


def consume_approval(sha256: str) -> bool:
    # ENG-00734: single-use no longer rests on "the source was renamed away" -- measured
    # (ENV-TWO-CONCURRENT-OS-REPLACE-CALLS-ONTO-ONE-TARGET-CAN-BOTH-SUCCEED-ON-WINDOWS) two
    # real processes racing `os.replace` on the SAME source both return success in 9 of 10
    # trials. Single-use now rests on "exactly one caller can create this path"
    # (`O_CREAT|O_EXCL`), which is the trap registry's own `safe_alternative` for this trap,
    # measured exclusive in 20 of 20 four-racer trials. The rename below is retained only as
    # a best-effort cleanup of the source; it is NOT the safety mechanism.
    #
    # Repaired 2026-09-22: this copy now writes and
    # requires `approved_under` under the same label the host hook uses. It previously
    # kept the retired `approved_by`, and the comment here said so and deferred the fix.
    # A receipt written by an older copy no longer validates -- deliberately, because that
    # receipt carries the very attestation claim the relabel exists to withdraw, and these
    # receipts are single-use with an expiry measured in minutes, so the window in which
    # one can exist at all is bounded by its own design.
    path = config.state_root() / "approvals" / f"{sha256}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    expires_at = _parse_timestamp(payload.get("expires_at"))
    created_at = _parse_timestamp(payload.get("created_at"))
    valid = (
        payload.get("schema") == SCHEMA
        and payload.get("command_sha256") == sha256
        and payload.get("approved_under") == APPROVAL_RULE_LABEL
        and payload.get("uses_remaining") == 1
        and expires_at is not None
        and expires_at > _utc_now()
        and created_at is not None
        and all(str(payload.get(key, "")).strip() for key in (
            "reason", "alternatives_considered", "baseline_reuse_plan"
        ))
    )
    if not valid:
        return False
    # The claim key is the approval's own `created_at`, PARSED then reformatted from the
    # parsed datetime's own components -- no payload text ever reaches a path -- at
    # microsecond granularity, measured 5/5 distinct across back-to-back records in one
    # process. This also closes the audit-overwrite defect in today's whole-second key
    # (`int(_utc_now().timestamp())`): on the now-impossible collision, `O_EXCL` REFUSES
    # rather than silently overwriting the earlier consumption record.
    key = created_at.strftime("%Y%m%dT%H%M%S.%f")
    consumed = config.state_root() / "consumed" / f"{sha256}.{key}.json"
    consumed.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    stamp = dict(payload)
    stamp["consumed_at"] = _utc_now().isoformat().replace("+00:00", "Z")
    stamp["consumed_claim_token"] = token
    try:
        # THE CLAIM. One syscall. Catch ANY OSError, not just `FileExistsError`: an existing
        # DIRECTORY at this claim path measures `PermissionError` errno 13 on this platform,
        # not `FileExistsError`.
        handle = os.open(str(consumed), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return False
    try:
        os.write(handle, (json.dumps(stamp, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    finally:
        os.close(handle)
    # Defence in depth, kept from the trap registry's own remedy: measured (ENG-00734
    # design, M2b) to change no outcome over the primitive alone, in case some future state
    # directory's filesystem does not honour exclusive create the way this one does.
    try:
        written = json.loads(consumed.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if written.get("consumed_claim_token") != token:
        return False
    try:
        path.unlink()  # best effort. NOT the safety mechanism -- see the module note above.
    except OSError:
        pass
    return True


def _audit(event: str, sha256: str, findings: tuple[dict[str, str], ...]) -> None:
    path = config.state_root() / "events.jsonl"
    payload = {
        "timestamp": _utc_now().isoformat().replace("+00:00", "Z"),
        "event": event,
        "command_sha256": sha256,
        "rule_ids": [item["rule_id"] for item in findings],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    except OSError:
        pass


def block_reason(sha256: str, findings: tuple[dict[str, str], ...]) -> str:
    details = "\n".join(
        f"- {item['rule_id']}: {item['activity']}; cheaper alternative: {item['alternative']}."
        for item in findings
    )
    return (
        "COST-PROPORTIONAL EXECUTION GATE: this command is blocked before execution.\n\n"
        f"{details}\n\nCommand SHA-256: {sha256}\n\n"
        "First determine whether a cheaper, faster method can provide enough confidence. "
        "If the heavy operation is still necessary, explain its expected time/I/O, alternatives, "
        "confidence benefit, and reusable-baseline plan to the user. After explicit user approval, "
        "record one expiring use for this exact SHA with this hook's --approve-command-sha mode, "
        "then retry the unchanged command. Do not self-authorize."
    )


def run_hook(payload: Mapping[str, object]) -> dict[str, str] | None:
    if not arming.is_armed("execution_guard"):
        return None
    command = extract_command(payload)
    if command is None:
        return None
    # Classify the PAYLOAD-STRIPPED copy -- a heredoc's or here-string's body is not going
    # to execute, so it must not be scanned as if it were the command. Hashing and
    # approval below still use the ORIGINAL command unchanged.
    findings = classify_command(strip_payload_bodies(command))
    if not findings:
        return None
    sha256 = command_sha256(command)
    if consume_approval(sha256):
        _audit("approved_override_consumed", sha256, findings)
        return None
    _audit("blocked", sha256, findings)
    return {"decision": "block", "reason": block_reason(sha256, findings)}


def _approval_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Record one explicit heavy-command approval")
    parser.add_argument("--approve-command-sha", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--alternatives", required=True)
    parser.add_argument("--baseline-plan", required=True)
    parser.add_argument("--expires-minutes", type=int, default=None)
    args = parser.parse_args(argv)
    path = record_approval(
        args.approve_command_sha,
        reason=args.reason,
        alternatives=args.alternatives,
        baseline_plan=args.baseline_plan,
        expires_minutes=args.expires_minutes,
    )
    print(path.name)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args:
        return _approval_cli(args)
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, Mapping):
        return 0
    decision = run_hook(payload)
    if decision is not None:
        print(json.dumps(decision, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
