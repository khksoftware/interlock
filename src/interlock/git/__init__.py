# SPDX-License-Identifier: Apache-2.0
"""interlock.git: refusals that fire at the moment a git action is attempted.

Five gates -- `protected_paths`, `absolute_local_path`, `stash_invocation`,
`synthetic_git_identity`, `commit_message_pattern` -- each a `pre-commit`, `commit-msg`,
or `reference-transaction` hook. See ``README.md`` at the root of this distribution for
what this host is and why it exists, ``docs/INTEGRATION.md`` for installing it into a
repository (alone, or alongside `interlock.turn`), and ``docs/USAGE.md`` for authoring a
new gate of this class.

This subpackage does not import :mod:`interlock.turn`, and nothing in it requires
`interlock.turn` to be configured, wired, or even present -- see ``README.md``'s section
on independent adoption.
"""
from __future__ import annotations
