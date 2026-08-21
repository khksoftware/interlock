# SPDX-License-Identifier: Apache-2.0
"""Refuse a commit made under a synthetic (reserved-domain) git identity left over in config.

## The gap this closes

`git config --local user.name`/`user.email` is per-repository and persists silently. Setting
either to prove some identity-sensitive behaviour, then forgetting to unset it afterward,
silently authors EVERY subsequent commit in every worktree sharing that repository, in every
stream working in it -- until someone happens to notice a commit's author field. Nothing
warns: the author field is not read by any gate, any test, or any human in the ordinary
course of committing.

## Why this is observable at the commit-time boundary

A commit's author identity is exactly what `git config --get user.email`/`user.name` resolves
to at the moment of the commit, and a `pre-commit` hook runs with the same working directory
and environment a real commit would -- so it observes precisely the value about to be burned
into the commit object a moment later. This is a genuinely observable action-boundary case.

## Scope: config, not content

Unlike every other gate in this package, this predicate does not read the commit's
changed-path set at all -- the defect it closes is a persistent, repository-level config
value that silently authors EVERY later commit regardless of what that commit touches, so
this predicate is checked unconditionally, on every commit, matching the shape of the defect
it closes.

## What is matched, and why narrowly

:data:`SYNTHETIC_IDENTITY_EMAIL_PATTERN` matches the IANA-reserved documentation/example
domains (RFC 2606: `example.com`, `example.org`, `example.net`, `example.invalid`) and
`localhost`. No real contributor's mailbox can legitimately live at any of these -- they are
reserved precisely so nothing real ever does -- so this predicate has no plausible
false-positive against an actual human co-author. It is deliberately narrow rather than a
general "does this look synthetic" guess: widening it further (e.g. refusing any address
containing "test" or "proof") would risk refusing a legitimate contributor's real address.
"""
from __future__ import annotations

import re
from pathlib import Path

from interlock.git.hookkit import GateSpec, render_shim
from interlock.plumbing import effective_git_config

GATE_LABEL = "synthetic-git-identity gate"
GATE_MARKER_NAME = "interlock-git-synthetic-git-identity"
HOOK_NAME = "pre-commit"
CLI_MODULE = "interlock.git.cli.check_synthetic_git_identity"

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

#: The IANA-reserved documentation/example domains (RFC 2606) plus `localhost`. Nothing real
#: is ever legitimately reachable at any of these, so matching them carries no plausible
#: false-positive against a genuine human co-author.
SYNTHETIC_IDENTITY_EMAIL_PATTERN = re.compile(
    r"@(example\.(com|org|net|invalid)|localhost)$", re.IGNORECASE
)


def synthetic_identity_failures(repository_root: str | Path) -> tuple[str, ...]:
    """Every configured identity field that matches a known-synthetic pattern.

    Checked unconditionally, on every commit, regardless of what that commit touches -- the
    defect this closes is a persistent config value, not something scoped to a particular
    file.
    """
    root = Path(repository_root)
    failures: list[str] = []
    email = effective_git_config(root, "user.email")
    if email is not None and SYNTHETIC_IDENTITY_EMAIL_PATTERN.search(email):
        failures.append(
            f"user.email is {email!r}, a reserved documentation/example address. This looks "
            "like residue from proving some identity-sensitive behaviour rather than a real "
            "contributor. Unset it: `git config --local --unset user.email` (or scope the "
            "one command that needed it with `git -c user.email=... commit ...` instead of "
            "writing it into config at all)."
        )
    return tuple(failures)


__all__ = (
    "CLI_MODULE", "GATE_LABEL", "GATE_MARKER_NAME", "HOOK_NAME", "SPEC",
    "SYNTHETIC_IDENTITY_EMAIL_PATTERN", "synthetic_identity_failures",
)
