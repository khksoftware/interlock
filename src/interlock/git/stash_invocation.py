# SPDX-License-Identifier: Apache-2.0
"""Refuse a `git stash` invocation at the one point it is actually observable.

## Why `pre-commit` and `commit-msg` do not apply

`git stash` does not go through `git commit` at all -- it builds its commit objects with
`commit-tree` plumbing specifically so stashing partially-staged work does not re-run
commit-time checks. A `pre-commit` or `commit-msg` gate (see
:mod:`interlock.git.protected_paths` and :mod:`interlock.git.commit_message_pattern`) sees
nothing of a stash operation at all: verified directly, in a throwaway sandbox, that
`git stash push/pop/apply/drop/clear` fire none of `pre-commit`, `prepare-commit-msg`,
`commit-msg`, or `post-commit`, in any position tried.

## What DOES observe it: `reference-transaction`, keyed on the ref name

`reference-transaction` (`githooks(5)`, Git 2.28+) fires for every ref-transaction git
performs, receiving the transaction's phase as `$1` (`prepared`, `committed`, or `aborted`)
and the batch of ref updates on stdin, one `<old-value> SP <new-value> SP <ref-name>` triple
per line. Creating a stash (`git stash` / `git stash push`) fires it naming exactly
`refs/stash`; so does `git stash clear`; so does a `git stash pop`/`drop` that happens to
remove the LAST remaining entry (also a `refs/stash` deletion). Per `githooks(5)`, only a
non-zero exit during the `prepared` phase has any effect -- it aborts the transaction;
`committed` and `aborted` report on an already-decided outcome and their exit status is
ignored by git. That is the one moment this gate refuses at.

A refusal at `prepared` leaves the working tree byte-for-byte as it was before the attempt and
creates no stash entry at all: `git stash` exits non-zero (`fatal: ref updates aborted by
hook`) before it removes anything from the working tree.

## The honest limit -- stated rather than smoothed over

**A `git stash drop` (or `pop`, which is apply-then-drop) that leaves at least one OTHER stash
entry in the stack afterward is invisible to this hook, and to every hook git exposes.** Git's
stash-drop code path rewrites the stash reflog directly, bypassing the `refs_transaction_*`
API `reference-transaction` observes, UNLESS the drop empties the stash entirely (deleting
`refs/stash` outright), which goes through that API and is caught the same way `clear` is.

**Net effect, stated as a boundary rather than a hedge:** this gate reliably refuses stash
CREATION (`git stash`, `git stash push`, `git stash save`) and `git stash clear`, leaving the
working tree, index and stash list exactly as they were. A `pop`/`drop` of the SOLE remaining
entry is refused too (the `refs/stash` deletion IS observable), but by the time that
sub-transaction reaches the hook, the pop's own merge into the working tree has already
happened -- refusing the ref update does not undo it, only prevents the stash list from being
silently emptied and fails the command loudly rather than letting it succeed silently. A
`pop`/`drop` that leaves other entries in the stack is not seen at all: this is a property of
what git exposes, not a shortfall in this module, and it is the sharpest residual case a
"never stash" rule can have -- a pre-existing entry belonging to someone else, popped while
further entries remain, invisible to every hook available.

## Confirmed harder to bypass than a pre-commit gate, on one axis

`git stash --no-verify` does not exist as a flag -- git rejects it outright with `error:
unknown option`, unlike `git commit --no-verify`. The remaining bypasses are the ones every
hook-based gate shares: repointing `core.hooksPath`, and deleting this gate's own arming
marker.
"""
from __future__ import annotations

from interlock.git.hookkit import GateSpec

GATE_LABEL = "stash-invocation gate"
GATE_MARKER_NAME = "interlock-git-stash-invocation"
HOOK_NAME = "reference-transaction"
CLI_MODULE = "interlock.git.cli.check_stash_invocation"

#: The one ref this gate cares about. Exact match, not a prefix -- git's stash mechanism uses
#: exactly this one ref, never a namespaced variant.
STASH_REF = "refs/stash"

#: The only phase during which the hook's exit status has any effect on the transaction.
#: `committed` and `aborted` report on an already-decided outcome; refusing then would be
#: theater, not a refusal.
ACTIONABLE_PHASE = "prepared"

#: `reference-transaction` has an unusual calling convention (phase as `$1`, transaction body
#: on stdin), so this shim is hand-written rather than built from
#: :func:`interlock.git.hookkit.render_shim` -- it needs `"$@"` forwarded and relies on stdin
#: being inherited automatically by `exec`, which the generic helper's default (no-argument)
#: shape does not cover.
HOOK_SHIM = f"""#!/bin/sh
# interlock (git): {GATE_LABEL}. INSTALLED, NOT TRACKED.
#
# This file deliberately holds no logic. Everything it could get wrong lives in the tracked,
# tested module this shim execs, and its own test suite asserts this file is present and
# byte-identical to the shim it carries.
#
# Hooks resolve to the git COMMON directory, so this fires in every worktree of a repository
# it is installed into. It therefore refuses to enforce anywhere it was not explicitly armed.
# The arming marker lives in the PER-WORKTREE git directory; an unarmed worktree exits 0
# having loaded nothing.
#
# git invokes this hook as `reference-transaction <phase>` with the batch of ref updates on
# stdin. Only a non-zero exit during the `prepared` phase has any effect.
set -e
gate_dir="$(git rev-parse --git-dir)"
gate_marker="$gate_dir/{GATE_MARKER_NAME}"
[ -f "$gate_marker" ] || exit 0
gate_python="$(cat "$gate_marker")"
if [ ! -f "$gate_python" ]; then
    printf '%s\\n' "{GATE_LABEL}: the recorded interpreter is absent: $gate_python" >&2
    printf '%s\\n' "reinstall with: <interpreter> -m {CLI_MODULE} --install" >&2
    printf '%s\\n' "the transaction is refused rather than passed unchecked." >&2
    exit 1
fi
exec "$gate_python" -B -m {CLI_MODULE} "$@"
"""

SPEC = GateSpec(
    marker_name=GATE_MARKER_NAME, hook_name=HOOK_NAME, shim=HOOK_SHIM,
    cli_module=CLI_MODULE, gate_label=GATE_LABEL,
)


def transaction_touches_stash_ref(phase: str, transaction_stdin: str) -> bool:
    """True iff this reference-transaction batch would create, move or delete `refs/stash`,
    during the one phase where refusing still has effect.

    `transaction_stdin` is one `<old-value> SP <new-value> SP <ref-name>` triple per line.
    Git ref names never contain whitespace and neither does an object id, so splitting each
    line on the first two spaces reliably isolates the ref name as the remainder.
    """
    if phase != ACTIONABLE_PHASE:
        return False
    for line in transaction_stdin.splitlines():
        if not line.strip():
            continue
        parts = line.split(" ", 2)
        if len(parts) != 3:
            continue
        _old_value, _new_value, ref_name = parts
        if ref_name == STASH_REF:
            return True
    return False


def stash_invocation_refusal(phase: str, transaction_stdin: str) -> str | None:
    """A refusal message, or `None` if this transaction is not this gate's business."""
    if not transaction_touches_stash_ref(phase, transaction_stdin):
        return None
    return (
        "this reference transaction creates, moves or deletes `refs/stash` -- a `git stash` "
        "invocation is in progress and this repository's standing rule is to never stash: "
        "the stack is shared across every worktree, live entries belonging to other work may "
        "sit in it, and a bare pop takes the top one rather than yours. Refused before the "
        "ref lands; the working tree and index are unaffected by this refusal."
    )


__all__ = (
    "ACTIONABLE_PHASE", "CLI_MODULE", "GATE_LABEL", "GATE_MARKER_NAME", "HOOK_NAME",
    "HOOK_SHIM", "SPEC", "STASH_REF", "stash_invocation_refusal", "transaction_touches_stash_ref",
)
