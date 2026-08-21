# SPDX-License-Identifier: Apache-2.0
"""The one exception type the git-action host raises.

A gate that cannot establish whether an action is safe is not the same fact as an action
being unsafe. Every predicate and every CLI in :mod:`interlock.git` keeps
that distinction: a :class:`GateError` means "I could not judge this," and the caller
decides to fail closed (refuse) rather than treating the exception as "this action is
fine." Nothing raises :class:`GateError` to report a refused commit, stash, or message --
that is always a plain return value (an empty tuple means clean; a non-empty tuple means
refused).

**Why this lives at the shared root rather than inside ``interlock.git``.** The class itself is
host-neutral machinery -- a plumbing-level "I could not determine this" signal -- and
:mod:`interlock.plumbing` (imported by both hosts) needs somewhere host-neutral
to raise it from. `interlock.turn` does not raise it and is not expected to: every hook in that
package is deliberately fail-OPEN (an unreadable transcript or malformed payload resolves
to "nothing to check," never an exception), which is a stated, deliberate asymmetry between
the two hosts -- see `interlock.git`'s README section on failing closed versus `interlock.turn`'s on
failing open. Importing this module carries no cost either way: it declares one class and
has no other import of its own.
"""
from __future__ import annotations


class GateError(RuntimeError):
    """The gate could not be established or run.

    Raised for environmental problems only: not a git repository, git itself unreadable, a
    missing interpreter to arm with, a hook file already occupied by something foreign.
    Never raised to report that a commit, stash, or message violates a gate's rule -- that
    is always a plain, empty-or-not tuple return.
    """


__all__ = ("GateError",)
