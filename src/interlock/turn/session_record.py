# SPDX-License-Identifier: Apache-2.0
"""Shared reader for the one JSON file the two roster hooks both depend on.

`idle_roster.py` and `roster_reconciliation.py` ask two different questions about the same
underlying record: is the roster verified-empty while work sits ready, and does the
roster match what the transcript itself shows was dispatched. Both questions need the
same three primitives -- read the record, find the platform's node inside it, and know
whether its roster is verified-empty -- so those primitives live here once rather than
being copied into each hook file twice.

This is possible, and is a deliberate difference from the internal framework this package
was extracted from, because this package is installed as a real Python distribution
(`pip install -e`) rather than deployed as a set of standalone copy-pasted script files.
A hook that needs to be a single self-contained file with no import context of its own
cannot share code this way; a hook installed from a proper package can.

## The session record's schema

A minimal example with one platform, one ready row, and an empty roster:

```json
{
  "platforms": [
    {
      "platform": "default",
      "roster": {"state": "none", "entries": []},
      "queue": [
        {"id": "PROJ-101", "status": "queued", "sequenced": true}
      ]
    }
  ]
}
```

- **`platforms`** is a list of nodes, one per harness/agent platform driving this
  repository (Claude Code, Codex, or whatever else you run). A single-platform adopter
  may omit the wrapper entirely and put `roster`/`queue` at the document's top level
  instead -- see `platform_node` below for exactly how that fallback resolves.
- **`roster.state`** is one of three values, deliberately never collapsed into each
  other: `"none"` (something looked and found nothing running), `"not-observable"`
  (nobody could look), or `"enumerated"` (a real, current list of running agents is in
  `roster.entries`). Only `"none"` with an empty `entries` list counts as
  *verified*-empty -- `"not-observable"` must never read as idle capacity.
- **`queue`** is a flat list of work rows. A row is *dispatchable* when it reads
  `status: "queued"`, `sequenced: true` (the supervisor has placed it in the order --
  an unsequenced row is not idle capacity for anyone to complain about), and carries no
  non-empty `blocked_on`. `id` is a free-text board/ticket identifier used for
  cross-referencing against a live dispatch's own description (see
  `roster_reconciliation.py`).

Every field not listed above is ignored by this module; add whatever else your own
tooling needs to the record without breaking either hook.
"""
from __future__ import annotations

import json
from pathlib import Path

from interlock.plumbing import repository_root as _repository_root


def repository_root(cwd: str | None = None) -> Path | None:
    """The repository this hook is being asked about, resolved from git. Never raises.

    A thin, host-facing alias of :func:`interlock.plumbing.repository_root` -- kept here so
    every existing caller in this host (and its tests) can keep writing `sr.repository_root()`
    without reaching into the shared plumbing module directly.
    """
    return _repository_root(cwd)


def load_record(path: Path) -> dict | None:
    """Read and parse the session record. Never raises; returns None on any failure."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def platform_node(document: dict, platform: str | None = None) -> dict | None:
    """This platform's node, or None when the record has none.

    A record carrying a `platforms` list is searched by name (first entry when
    `platform` is None). A record with no `platforms` key at all is treated as a
    single-platform document and returned as-is -- the documented fallback for an
    adopter who does not need the multi-platform wrapper.
    """
    platforms = document.get("platforms")
    if isinstance(platforms, list):
        for node in platforms:
            if not isinstance(node, dict):
                continue
            if platform is None or node.get("platform") == platform:
                return node
        return None
    if "roster" in document or "queue" in document:
        return document
    return None


def roster_is_empty(node: dict) -> bool:
    """True only for a VERIFIED-empty roster.

    `"none"` means somebody probed and found nothing. `"not-observable"` means nobody
    could look. The two are never collapsed here, the same as everywhere else this
    schema is read.
    """
    roster = node.get("roster")
    if not isinstance(roster, dict):
        return False
    return roster.get("state") == "none" and not (roster.get("entries") or ())


def row_is_sequenced(row: dict) -> bool:
    value = row.get("sequenced")
    return bool(value) if isinstance(value, bool) else False


def dispatchable_rows(node: dict, exemptions: dict[str, str] | None = None) -> list[str]:
    """Ids of every row that is `queued`, sequenced, unblocked, and not exempted.

    `exemptions` maps an id to a human-readable reason it is genuinely not
    dispatchable for a cause this schema has no field for (see the module docstring on
    `config.SESSION_BOUNDARY_ROWS_PATH`). An entry with no reason is not a valid
    exemption -- callers should validate that separately if they load exemptions from
    adopter-supplied data.
    """
    exemptions = exemptions or {}
    ready: list[str] = []
    for row in node.get("queue") or ():
        if not isinstance(row, dict):
            continue
        identifier = str(row.get("id", "")).strip().strip("`")
        if row.get("status") != "queued":
            continue
        if not row_is_sequenced(row):
            continue
        if str(row.get("blocked_on") or "").strip():
            continue
        if identifier in exemptions:
            continue
        if identifier:
            ready.append(identifier)
    return ready


def register_ids(node: dict) -> tuple[str, ...]:
    """Upper-cased `id` values the roster's own `entries` currently enumerate."""
    roster = node.get("roster")
    if not isinstance(roster, dict):
        return ()
    ids: list[str] = []
    for entry in roster.get("entries") or ():
        if isinstance(entry, dict):
            value = str(entry.get("id", "")).strip()
            if value:
                ids.append(value.upper())
    return tuple(ids)


def register_state(node: dict) -> str | None:
    roster = node.get("roster")
    if not isinstance(roster, dict):
        return None
    value = roster.get("state")
    return value if isinstance(value, str) else None


def a_quiescing_command_is_running(transcript_path: str | None, quiescing_commands: tuple[str, ...],
                                    lookback_entries: int = 400) -> bool:
    """Is this session deliberately winding down rather than idling?

    Fires only while one of `quiescing_commands` appears in the recent transcript, so it
    expires on its own once the transcript moves on. Never raises: an unreadable
    transcript resolves to False, which leaves the caller's own check ARMED -- the safe
    direction, because a missing suppression costs one explained turn while a spurious
    one silently hides a real gap.
    """
    if not transcript_path or not quiescing_commands:
        return False
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except Exception:
        return False

    for raw in reversed(lines[-lookback_entries:]):
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
        blob = json.dumps(entry.get("message") or entry)
        for name in quiescing_commands:
            if f"<command-name>/{name}" in blob or f'"skill": "{name}"' in blob:
                return True
    return False
