# SPDX-License-Identifier: Apache-2.0
"""Interlock -- a constraint that cannot be forgotten, because the action will not proceed.

An interlock, in engineering, is a device that makes an action *impossible* unless a
condition holds: the press that will not cycle with the guard open, the chamber door that
will not release under pressure. Not a warning. Not a checklist. Not a reminder. The
action does not proceed. This package is that idea applied to two boundaries an AI-assisted
development workflow actually has:

- :mod:`interlock.git` -- refusals at the moment a **git action** is attempted
  (`pre-commit`, `commit-msg`, `reference-transaction`).
- :mod:`interlock.turn` -- refusals and reminders at the moment an **agent turn** is about
  to end or begin (a supervisor/worker dispatch loop's own hook events).

Real interlocks are installed per-machine and deliberately engaged, not merely present --
a guard door wired in but never armed protects nobody. That is not a coincidence borrowed
for the name: both host modules here share one install-and-arm discipline (see
:mod:`interlock.arming`) for exactly that reason. See ``README.md`` at the root of this
distribution for what the two hosts share and ``docs/INTEGRATION.md`` for installing
either one alone, or both together -- neither subpackage imports the other, and neither
requires the other's configuration, state, or install step to function.
"""
from __future__ import annotations

__version__ = "0.2.0"

__all__ = ("__version__",)
