# SPDX-License-Identifier: Apache-2.0
r"""Refuse a commit whose message carries a trailer matching a forbidden pattern.

## The gap this closes

A rule about what a commit message may or must not say -- "no vendor attribution," "every
commit must reference a ticket," "no `Reviewed-by` without a matching approval record" -- is
ordinarily enforced by asking people (or agents) to remember it. This gate is the generic
corrective: a configurable trailer-key set and a configurable set of forbidden value
patterns, checked at the one point a commit's message is fixed but the commit object does not
exist yet.

The built-in default (:data:`DEFAULT_TRAILER_KEYS`, :data:`DEFAULT_FORBIDDEN_PATTERNS`) closes
one concrete, common instance of the general rule: a coding assistant's harness silently
injecting a `Co-Authored-By: <vendor/model>` trailer into every commit it makes, regardless of
what any project's own policy says about it. That default is a convenience, not the point --
every argument below accepts a caller-supplied trailer-key set and pattern list instead, for a
project enforcing a different rule of the identical shape.

## Why this is a `commit-msg` hook, not `pre-commit`

A `pre-commit` gate's subject is staged FILE content, which the index already holds before
the commit message is ever written. A trailer lives in the commit MESSAGE, which does not
exist yet when `pre-commit` runs -- git's own hook ordering is `pre-commit`, then
`prepare-commit-msg`, then the editor (if any), then `commit-msg`, then the commit object is
created. `commit-msg` is therefore a structurally separate hook file, dispatched on a
different git event, not a wider `pre-commit` predicate.

## Match shape: trailer, not keyword

Matching on a bare keyword ("does the message contain the word X anywhere") would refuse a
commit that merely DISCUSSES the forbidden term in its subject or body -- including, notably,
the commit that lands this very gate, whose message necessarily discusses what it refuses.
So the match is two-part, both required:

1. **Trailer shape.** The line must parse as a git trailer -- `Key: value`, key starting with
   a letter -- and its KEY, normalized (case folded, whitespace/underscores collapsed to a
   single hyphen), must be one of the configured trailer keys. Prose anywhere else in the
   subject or body is never inspected for content; only trailer-shaped lines are.
2. **A forbidden pattern in the VALUE.** Even a trailer-shaped line is not itself the defect
   -- a human co-author's trailer is legitimate. The value must additionally match one of the
   configured forbidden patterns.

## Which content

A `commit-msg` hook receives exactly one argument: the path to a file holding the proposed
commit message. :func:`read_commit_message` reads that file verbatim as UTF-8, explicit
rather than left to the platform default.

## What it does not reach

Scoped to the message of the commit being made, nothing else -- it does not scan file
content (:mod:`interlock.git.absolute_local_path` and
:mod:`~interlock.git.protected_paths` do that, an unrelated surface) and
it does not audit already-committed history. And, like every hook-based gate, it is
bypassable (`--no-verify`, a repointed `core.hooksPath`, a deleted marker); it raises the cost
of a forbidden trailer reaching a commit, it does not make one impossible.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from interlock.config import load_config, section
from interlock.git.hookkit import GateSpec, render_shim

GATE_LABEL = "commit-message-pattern gate"
GATE_MARKER_NAME = "interlock-git-commit-message-pattern"
HOOK_NAME = "commit-msg"
CLI_MODULE = "interlock.git.cli.check_commit_message_pattern"

SPEC = GateSpec(
    marker_name=GATE_MARKER_NAME,
    hook_name=HOOK_NAME,
    shim=render_shim(
        marker_name=GATE_MARKER_NAME, hook_name=HOOK_NAME, cli_module=CLI_MODULE,
        gate_label=GATE_LABEL, forwards_hook_arguments=True,
    ),
)

#: A git-trailer-shaped line: `Key: value`, key starting with a letter, value non-empty.
#: Matched per line, never against the whole message, so a match can never span lines.
TRAILER_LINE_PATTERN = re.compile(r"^\s{0,3}(?P<key>[A-Za-z][\w-]*)\s*:\s*(?P<value>\S.*)$")

#: Trailer keys this gate's default configuration treats as an authorship claim. A project
#: enforcing a different rule (e.g. "every `Fixes:` trailer must reference an open issue")
#: supplies its own set instead -- see the ``trailer_keys`` argument below.
DEFAULT_TRAILER_KEYS: frozenset[str] = frozenset({"co-authored-by"})

#: A representative, openly-extensible default: known AI vendor/model/harness identities that
#: make a `Co-Authored-By` trailer an attribution claim rather than an ordinary human
#: co-author. This is a convenience default, not the point of the module -- see
#: ``forbidden_patterns`` below for supplying a project's own list instead.
DEFAULT_FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in (
        ("Claude", r"\bclaude\b"),
        ("Anthropic", r"\banthropic\b"),
        ("ChatGPT", r"\bchat[- ]?gpt\b"),
        ("OpenAI", r"\bopenai\b"),
        ("GPT (bare model name)", r"\bgpt-\d|\bgpt\b"),
        ("Codex", r"\bcodex\b"),
        ("GitHub Copilot", r"\bcopilot\b"),
        ("Gemini", r"\bgemini\b"),
        ("Cursor", r"\bcursor\b"),
        ("Windsurf", r"\bwindsurf\b"),
        ("Devin", r"\bdevin\b"),
        ("generic AI-assistant self-description", r"\bai\s+assistant\b|\blanguage\s+model\b"),
    )
)


def _normalize_trailer_key(key: str) -> str:
    """`Co-Authored-By`, `co-authored-by`, `Co Authored By` and `CO_AUTHORED_BY` all
    normalize to the same string."""
    normalized = re.sub(r"[\s_]+", "-", key.strip().lower())
    return re.sub(r"-+", "-", normalized)


def commit_message_pattern_failures(
    message: str, *,
    trailer_keys: frozenset[str] | None = None,
    forbidden_patterns: Sequence[tuple[str, re.Pattern[str]]] | None = None,
) -> tuple[str, ...]:
    """Every trailer-shaped line in ``message`` matching a forbidden pattern.

    Pure function over the message text -- no I/O, no git -- so it is directly testable and
    is also what :func:`staged_commit_message_pattern_failures` calls after reading the file
    git hands the hook.
    """
    keys = trailer_keys if trailer_keys is not None else DEFAULT_TRAILER_KEYS
    patterns = forbidden_patterns if forbidden_patterns is not None else DEFAULT_FORBIDDEN_PATTERNS
    failures: list[str] = []
    for line_number, raw_line in enumerate(message.splitlines(), start=1):
        match = TRAILER_LINE_PATTERN.match(raw_line)
        if not match:
            continue
        key, value = match.group("key"), match.group("value")
        if _normalize_trailer_key(key) not in keys:
            continue
        matched_labels = tuple(dict.fromkeys(
            label for label, pattern in patterns if pattern.search(value)
        ))
        if not matched_labels:
            continue
        failures.append(
            f"commit message line {line_number}: trailer {key!r} matches a forbidden pattern "
            f"({', '.join(matched_labels)}): " + repr(raw_line)
        )
    return tuple(failures)


def read_commit_message(path: str | Path) -> str:
    """The exact content git is proposing to commit, from the path a `commit-msg` hook is
    handed. Explicit UTF-8, never the platform default."""
    return Path(path).read_text(encoding="utf-8")


def staged_commit_message_pattern_failures(
    message_path: str | Path, *,
    trailer_keys: frozenset[str] | None = None,
    forbidden_patterns: Sequence[tuple[str, re.Pattern[str]]] | None = None,
) -> tuple[str, ...]:
    return commit_message_pattern_failures(
        read_commit_message(message_path), trailer_keys=trailer_keys,
        forbidden_patterns=forbidden_patterns,
    )


def staged_commit_message_pattern_failures_from_config(
    message_path: str | Path, *, repository_root: str | Path, config_path: str | Path | None = None,
) -> tuple[str, ...]:
    """Reads ``"commit_message_pattern"."trailer_keys"`` (a list of strings) from
    ``interlock.json`` if present; the built-in vendor/model defaults are used
    whenever no config section overrides them. Custom forbidden-pattern lists are a
    Python-level API (regex objects do not round-trip through JSON cleanly) -- call
    :func:`commit_message_pattern_failures` directly for that case.
    """
    config = section(load_config(repository_root, path=config_path), "commit_message_pattern")
    configured_keys = config.get("trailer_keys")
    trailer_keys = frozenset(configured_keys) if configured_keys is not None else None
    return staged_commit_message_pattern_failures(message_path, trailer_keys=trailer_keys)


__all__ = (
    "CLI_MODULE", "DEFAULT_FORBIDDEN_PATTERNS", "DEFAULT_TRAILER_KEYS", "GATE_LABEL",
    "GATE_MARKER_NAME", "HOOK_NAME", "SPEC", "TRAILER_LINE_PATTERN",
    "commit_message_pattern_failures", "read_commit_message",
    "staged_commit_message_pattern_failures", "staged_commit_message_pattern_failures_from_config",
)
