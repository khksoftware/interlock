# SPDX-License-Identifier: Apache-2.0
r"""Refuse a commit whose staged content embeds an absolute local filesystem path.

## The gap this closes

An absolute path on the machine that produced a commit -- a Windows drive-letter path under
someone's user profile, a POSIX home directory, a UNC network share -- is machine- and
person-specific content that should never end up in a tracked file: it tells a reader nothing
durable, and it can leak a username, a directory layout, or which machine did the work. The
instruction "never embed an absolute local path" is easy to state and easy to forget in the
middle of debugging a real
problem, which is exactly the shape of defect this package's mechanism class exists for:
measured repeatedly (see ``README.md``), a rule repeated in every brief, present at the
moment of the write, violated anyway. This gate is the corrective for that one instruction:
a refusal at the point of the commit, indifferent to whether anyone remembered anything.

## What is matched

:data:`ABSOLUTE_LOCAL_PATH_PATTERNS` is a small, deliberately generic set: a Windows
drive-letter path (a single letter, a colon, then a backslash or forward slash, then the
rest), a UNC network path (two leading backslashes, a server name, a share name), and a POSIX
home directory (the literal segment ``home`` or ``Users`` bracketed by path separators,
followed by a username segment and more). It is not exhaustive -- a project with its own local
convention (a fixed non-home mount point, a container path) may need to extend it, which is
exactly what the ``extra_patterns`` argument below is for.

## Line-break evasion: a narrow, join-aware second pass

Scanning line by line (see :func:`staged_absolute_local_path_failures`) is blind to a path
whose text is split across an ordinary line break -- a wrapped log paste, a hard-wrapped
table cell, an editor's soft wrap turned hard on save. Measured directly: for a Windows
drive path, only 2 of 32 break positions evade (both inside the three-character
``letter:separator`` sequence every pattern requires before it can match at all); for a
POSIX ``/home/`` or ``/Users/`` path, roughly a third of break positions evade, and the
same is true for a UNC path -- because those patterns' own required, un-skippable prefix
(``/home/`` plus a username segment plus a trailing ``/``; a UNC path's own leading
``\\SERVER\SHARE``) spans more characters than a Windows drive prefix does, so more break
points fall inside it.

The repair is deliberately **narrow, not a blanket whole-file join**: a blanket join --
concatenating every line in the file and scanning the result -- was rejected. This
package's own design principle is that a false refusal trains the bypass (see
``README.md``), and joining indiscriminately turns any line ending in what looks like a
drive letter, followed by any line starting with what looks like a path separator,
anywhere in the file, into a spurious match, regardless of whether the two lines have
anything to do with each other. Instead, this module re-scans only **adjacent** line
pairs, and only when the join point itself -- the last character of the first line, or
the first character of the second -- is a path separator (``/`` or ``\``) or a colon (the
character a Windows drive letter is immediately followed by). That is a superset check
only: the same patterns above still have to match the reconstructed two-line text, with
the match itself spanning the join, before anything is reported -- so an innocent line
ending in a bare letter or starting with a colon for unrelated reasons (a sentence ending
"...Plan B" followed by a line starting ": call support", or a markdown definition list)
never produces a false positive merely because the join was attempted.

**What this still cannot see, even after the join-aware pass:**

- **A break strictly inside a path segment**, touching neither a separator nor a colon on
  either side (a hard character-width wrap that happens to fall mid-word, e.g. splitting
  ``jdoe`` into ``jd`` / ``oe``). The join point itself carries no signal that a path
  continues there, and re-joining on every arbitrary adjacent pair regardless of content is
  exactly the blanket join this design rejects.
- **A path wrapped across three or more lines**, where no single adjacent PAIR contains
  enough of the pattern's required prefix to match on its own (e.g. ``/home/`` split so
  that the leading ``/``, ``home``, and the trailing ``/`` each land on a different line).
  Only adjacent pairs are ever joined, never three lines at once.
- **A separator itself split** in some encoding where what "the separator" is is not a
  single character at the join point (this module only ever reasons about literal ``/``,
  ``\``, and ``:`` bytes).

This is a real, disclosed residue, not a completeness claim -- see ``README.md``'s
"Limits" section for how this gate's residue fits alongside every other gate's.

## Exemptions: a project needs a way to cite a path on purpose

Some legitimate content genuinely needs to show an absolute path as an illustrative example,
a historical citation, or a factual provenance record (a build log, a bug report quoting a
real stack trace). Refusing those unconditionally would make the gate a nuisance an adopter
routes around rather than a control they trust, so this module supports two, adopter-owned
JSON registries, both optional:

- **Citations** -- ``[{"path": "<repo-relative path>", "line_contains": "<substring>"}]``.
  A line in the named file that also contains the given substring is exempt. Narrow on
  purpose: it names the exact line, not the whole file.
- **Deferred scope** -- ``[{"path_prefix": "<prefix>"}]``. Everything under a given prefix is
  exempt outright. Coarser, and meant for a subtree this gate should simply not look at (a
  fixtures directory full of intentionally-realistic sample paths, for instance) rather than
  for routine exceptions.

Neither registry is read from disk unless a caller asks for the CLI's default behaviour
(loading them from ``interlock.json``, see :mod:`interlock.config`); a
caller may also pass either in directly, which is what every test in this package's own
suite does.

## Scope

Scoped to this commit's own changed-path set, exactly like every other gate here -- see
:mod:`interlock.git.protected_paths` for the same reasoning stated in
full. And, like every hook-based gate, this one is bypassable (``--no-verify``, a repointed
``core.hooksPath``, a deleted marker); it raises the cost of a leaked path reaching a commit,
it does not make one impossible.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from interlock.config import load_config, section
from interlock.git.hookkit import GateSpec, render_shim
from interlock.plumbing import commit_paths, index_blob

GATE_LABEL = "absolute-local-path gate"
GATE_MARKER_NAME = "interlock-git-absolute-local-path"
HOOK_NAME = "pre-commit"
CLI_MODULE = "interlock.git.cli.check_absolute_local_path"

SPEC = GateSpec(
    marker_name=GATE_MARKER_NAME,
    hook_name=HOOK_NAME,
    shim=render_shim(
        marker_name=GATE_MARKER_NAME, hook_name=HOOK_NAME, cli_module=CLI_MODULE,
        gate_label=GATE_LABEL,
    ),
    cli_module=CLI_MODULE,
    gate_label=GATE_LABEL,
)

#: Deliberately generic and deliberately small. See the module docstring on why: extend via
#: ``extra_patterns`` for a project's own local convention rather than growing this tuple to
#: cover every possible mount layout.
ABSOLUTE_LOCAL_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b[A-Za-z]:[\\/][^\s\"'`)>,;]*"),          # a drive letter, colon, separator
    re.compile(r"\\\\[^\s\"'`)>,;\\]+\\[^\s\"'`)>,;]*"),      # a UNC-shaped network path
    re.compile(r"/(?:home|Users)/[^\s\"'`)>,;/]+/[^\s\"'`)>,;]*"),  # a POSIX home directory
)


def _citation_lookup(entries: Sequence[Mapping[str, Any]]) -> dict[str, tuple[str, ...]]:
    lookup: dict[str, tuple[str, ...]] = {}
    for entry in entries:
        key = str(entry["path"])
        lookup[key] = lookup.get(key, ()) + (str(entry["line_contains"]),)
    return lookup


#: The characters that make a join point between two adjacent lines worth re-scanning: a
#: path separator, or the colon a Windows drive letter is immediately followed by. See the
#: module docstring's "Line-break evasion" section for why this is a superset check only --
#: the patterns themselves still have to match the reconstructed text before anything is
#: reported.
_JOIN_BOUNDARY_CHARS = ("/", "\\", ":")


def _is_path_shaped_join(first_line: str, second_line: str) -> bool:
    return first_line.endswith(_JOIN_BOUNDARY_CHARS) or second_line.startswith(_JOIN_BOUNDARY_CHARS)


def staged_absolute_local_path_failures(
    repository_root: str | Path, *,
    extra_patterns: Sequence[re.Pattern[str]] = (),
    citations: Sequence[Mapping[str, Any]] = (),
    deferred_scope: Sequence[Mapping[str, Any]] = (),
) -> tuple[str, ...]:
    """Every line (or adjacent line-break) in this commit's staged content that embeds an
    absolute local path.

    One finding per violating LINE, not one per overlapping pattern -- a line matched by two
    patterns at once is still a single thing to fix. A second, narrow pass then re-scans
    each adjacent line PAIR whose join point looks path-shaped (see
    :func:`_is_path_shaped_join` and the module docstring's "Line-break evasion" section),
    reporting a spanning match under the first line's number -- but never for a line already
    reported per-line, so a path that already triggered on one line alone is not reported
    twice just because its own boundary happens to look path-shaped too.
    """
    root = Path(repository_root)
    patterns = tuple(ABSOLUTE_LOCAL_PATH_PATTERNS) + tuple(extra_patterns)
    changed = commit_paths(root)
    citation_lookup = _citation_lookup(citations)
    deferred_prefixes = tuple(str(entry["path_prefix"]) for entry in deferred_scope)
    failures: list[str] = []
    for relative in changed:
        if any(relative.startswith(prefix) for prefix in deferred_prefixes):
            continue
        try:
            content = index_blob(root, relative)
        except UnicodeDecodeError:
            continue
        if content is None:
            continue
        needles = citation_lookup.get(relative, ())
        lines = content.splitlines()
        reported_lines: set[int] = set()
        for line_number, line in enumerate(lines, start=1):
            matches = [match.group(0) for pattern in patterns for match in pattern.finditer(line)]
            if not matches:
                continue
            if any(needle in line for needle in needles):
                continue
            reported_lines.add(line_number)
            reportable = tuple(dict.fromkeys(matches))
            failures.append(
                f"{relative}:{line_number} (the content this commit would carry): embeds an "
                "absolute local filesystem path: " + ", ".join(repr(m) for m in reportable)
            )
        for line_number in range(1, len(lines)):
            first_number, second_number = line_number, line_number + 1
            if first_number in reported_lines or second_number in reported_lines:
                continue  # already surfaced per-line; do not double-report the same content
            first_line, second_line = lines[line_number - 1], lines[line_number]
            if not _is_path_shaped_join(first_line, second_line):
                continue
            joined = first_line + second_line
            if any(needle in joined for needle in needles):
                continue
            split = len(first_line)
            spanning = tuple(dict.fromkeys(
                match.group(0)
                for pattern in patterns
                for match in pattern.finditer(joined)
                if match.start() < split < match.end()
            ))
            if not spanning:
                continue
            failures.append(
                f"{relative}:{first_number} (the content this commit would carry, continuing "
                f"onto line {second_number}): embeds an absolute local filesystem path split "
                "across the line break between these two lines: "
                + ", ".join(repr(m) for m in spanning)
            )
    return tuple(dict.fromkeys(failures))


def staged_absolute_local_path_failures_from_config(
    repository_root: str | Path, *, config_path: str | Path | None = None,
) -> tuple[str, ...]:
    """The same predicate, reading citations/deferred-scope from
    ``interlock.json`` (see :mod:`interlock.config`) if present.

    Config shape, under the ``"absolute_local_path"`` key::

        {
          "absolute_local_path": {
            "citations": [{"path": "...", "line_contains": "..."}],
            "deferred_scope": [{"path_prefix": "..."}]
          }
        }
    """
    root = Path(repository_root)
    config = section(load_config(root, path=config_path), "absolute_local_path")
    return staged_absolute_local_path_failures(
        root,
        citations=config.get("citations", ()),
        deferred_scope=config.get("deferred_scope", ()),
    )


__all__ = (
    "ABSOLUTE_LOCAL_PATH_PATTERNS", "CLI_MODULE", "GATE_LABEL", "GATE_MARKER_NAME", "HOOK_NAME",
    "SPEC", "staged_absolute_local_path_failures", "staged_absolute_local_path_failures_from_config",
)
