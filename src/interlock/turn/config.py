# SPDX-License-Identifier: Apache-2.0
"""Every adopter-specific knob this host reads, in one place, with its default.

Every hook module in this package reads its configuration through this module rather than
hardcoding a value inline -- the single most common way a framework like this one drifts
away from being portable is a project-specific constant quietly typed into a piece of
logic that otherwise has none. If you are adapting this package to a new project and find
yourself editing a hook module directly to change a name, a path, or a pattern, that is a
sign the value belongs here instead.

**Why environment variables stay the PRIMARY mechanism here, deliberately unlike
`interlock.git`'s JSON-file-first configuration.** A git-hook gate's CLI is invoked in a
process this package's own installer controls (the shim it writes), so a `--config <path>`
flag or a tracked JSON file at a known repository-relative location is a natural, low-
friction place to look. A turn-boundary hook is invoked by the HARNESS, per its own hook
configuration, and the one thing every harness reliably lets an adopter control at
hook-invocation time is the subprocess's own environment -- not a bespoke config-path
convention this package would have to teach every harness about. So every setting here has
an environment-variable override and a documented, deliberately generic default, exactly
as the package this host was extracted from did.

**Where this DOES share `interlock.git`'s single configuration file.**
:func:`session_boundary_rows` reads its adopter-owned exemption map from
`interlock.config`'s own `interlock.json`, `"turn"` section, `"session_boundary_rows"` key
-- unless `INTERLOCK_SESSION_BOUNDARY_ROWS_PATH` points somewhere else, in which case that
explicit path wins. This is the one setting genuinely worth sharing through the common file
rather than an environment variable: it is adopter-owned STRUCTURED data (an id-to-reason
map), not a short scalar, and an adopter already using `interlock.json` for `interlock.git`
gets this one for free without a second file to maintain. See ``docs/USAGE.md`` for what
each setting controls and how to override it.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- role labels --------------------------------------------------------------------
#
# The two-hat convention this host's role-label hook enforces: exactly one of these
# strings must open every assistant-authored message, and the SUPERVISOR label is the
# only one allowed to open the first message of a turn (the message that answers
# whoever is directing the session) -- see `role_label.py`.
SUPERVISOR_LABEL = os.environ.get("INTERLOCK_SUPERVISOR_LABEL", "[Supervisor]")
WORKER_LABEL = os.environ.get("INTERLOCK_WORKER_LABEL", "[Worker]")

# --- the session record --------------------------------------------------------------
#
# The one JSON file `idle_roster.py` and `roster_reconciliation.py` both read. See
# `docs/INTEGRATION.md` for its schema. Resolved relative to the repository root (found
# via `interlock.plumbing.repository_root`) unless given as an absolute path.
SESSION_RECORD_PATH = os.environ.get(
    "INTERLOCK_SESSION_RECORD_PATH", ".interlock/session_record.json"
)

# The exact platform node turn hooks read from a multi-platform session record.
# Missing configuration is deliberately generic; an explicitly empty or padded
# value remains malformed and is refused by `session_record.platform_node`.
SESSION_PLATFORM = os.environ.get("INTERLOCK_SESSION_PLATFORM", "default")

# --- quiescing commands ---------------------------------------------------------------
#
# Command or skill names that, when seen recently in the transcript, mean the session is
# deliberately winding down to a quiescent, empty-roster state -- both roster hooks
# suppress themselves entirely while one of these is running (see their module
# docstrings for why forcing a dispatch during a deliberate wind-down is the wrong
# failure direction). Comma-separated; empty means no suppression is ever applied.
QUIESCING_COMMANDS = tuple(
    name.strip()
    for name in os.environ.get("INTERLOCK_QUIESCING_COMMANDS", "wrap-up,prepare-to-pause").split(",")
    if name.strip()
)

# --- board-item id shape ---------------------------------------------------------------
#
# The regular expression `roster_reconciliation.py` uses to extract a board/ticket id from
# a dispatch's free-text description, case-insensitively. The default matches the common
# "PREFIX-NUMBER" shape most issue trackers use (`PROJ-123`, `OPS-7`, `TEAM-4567`, ...).
# Override this if your tracker's ids take a different shape.
ID_PATTERN = os.environ.get("INTERLOCK_ID_PATTERN", r"[A-Z][A-Z0-9]{1,9}-\d{1,6}")

# --- session-boundary exemptions -------------------------------------------------------
#
# Board-item ids that are genuinely not dispatchable for a reason the session record has
# no field for (see `idle_roster.py`'s own docstring on why this is a hand-maintained list
# with a written reason per entry, not a predicate). Empty by default -- this is
# adopter-owned data, not something this package ships pre-populated with. An explicit
# path here (a JSON file, resolved relative to the repository root unless absolute) wins
# over the shared `interlock.json` fallback described in the module docstring above.
SESSION_BOUNDARY_ROWS_PATH = os.environ.get("INTERLOCK_SESSION_BOUNDARY_ROWS_PATH", "")

# --- outstanding-agent registry ---------------------------------------------------------
#
# The best-effort, harness-user-level file `subagent_start.py` and `subagent_stop.py`
# maintain, and `user_prompt_submit.py` reads to decide whether to remind about a
# live-probe check. Deliberately NOT inside any repository -- see
# :mod:`interlock.turn.outstanding`'s own docstring for why a registry scoped to one
# session cannot be built from these two hook events alone.
OUTSTANDING_REGISTRY_PATH = os.environ.get(
    "INTERLOCK_OUTSTANDING_REGISTRY_PATH",
    str(Path.home() / ".interlock" / "outstanding-agents.json"),
)

# How long an entry may sit in that registry before `user_prompt_submit.py` treats it as
# stale and prunes it rather than reminding about it -- see that module's own docstring
# for why this exists (a crashed session that never fires the stop event otherwise leaves
# a permanent false-positive entry).
OUTSTANDING_STALE_SECONDS = int(os.environ.get("INTERLOCK_OUTSTANDING_STALE_SECONDS", str(6 * 60 * 60)))

# Slash-command or resumption-trigger prefixes after which the role-label reminder
# escalates -- the boundary where a self-applied labelling habit has actually been
# observed to drop in practice (see `user_prompt_submit.py`). Comma-separated.
RESUMPTION_COMMANDS = tuple(
    name.strip()
    for name in os.environ.get(
        "INTERLOCK_RESUMPTION_COMMANDS", "/resume,/compact,/clear"
    ).split(",")
    if name.strip()
)


def session_boundary_rows(repository_root: Path) -> dict:
    """Load the adopter-owned exemption map.

    Never raises: a missing or unreadable source means no exemptions, not an error --
    exemptions are an optional refinement, not something this package's own hooks depend
    on to run at all. Reads, in order: (1) the file named by
    `INTERLOCK_SESSION_BOUNDARY_ROWS_PATH` if set; (2) failing that, the `"turn"` section's
    `"session_boundary_rows"` key of the shared `interlock.json` (see the module docstring
    above); (3) failing that, `{}`.
    """
    if SESSION_BOUNDARY_ROWS_PATH:
        path = Path(SESSION_BOUNDARY_ROWS_PATH)
        if not path.is_absolute():
            path = repository_root / path
        try:
            import json
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    try:
        from interlock.config import load_config, section
        turn_section = section(load_config(repository_root), "turn")
        data = turn_section.get("session_boundary_rows", {})
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def resolved_session_record_path(repository_root: Path) -> Path:
    path = Path(SESSION_RECORD_PATH)
    if path.is_absolute():
        return path
    return repository_root / path
