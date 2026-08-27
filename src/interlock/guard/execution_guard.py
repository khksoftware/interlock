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
import re
import sys
from typing import Mapping

from interlock.guard import arming, config

SCHEMA = "interlock-guard-command-cost-approval/1.0"

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


def _atomic_json(path, payload: Mapping[str, object]) -> None:
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


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
        "approved_by": "explicit-user-authorization",
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
    path = config.state_root() / "approvals" / f"{sha256}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    expires_at = _parse_timestamp(payload.get("expires_at"))
    valid = (
        payload.get("schema") == SCHEMA
        and payload.get("command_sha256") == sha256
        and payload.get("approved_by") == "explicit-user-authorization"
        and payload.get("uses_remaining") == 1
        and expires_at is not None
        and expires_at > _utc_now()
        and all(str(payload.get(key, "")).strip() for key in (
            "reason", "alternatives_considered", "baseline_reuse_plan"
        ))
    )
    if not valid:
        return False
    import os

    consumed = config.state_root() / "consumed" / f"{sha256}.{int(_utc_now().timestamp())}.json"
    consumed.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(path, consumed)
    except OSError:
        return False
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
