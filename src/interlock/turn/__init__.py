# SPDX-License-Identifier: Apache-2.0
"""interlock.turn: refusals and reminders that fire at the boundary of an agent turn.

Turn-boundary checks for a supervisor/worker AI-agent dispatch loop -- refusals and
reminders that fire at the moment a turn is about to end or a dispatch is about to happen,
not at the moment a standing rule was written down somewhere. See ``README.md`` at the
root of this distribution for what this host is and why it exists, ``docs/INTEGRATION.md``
for wiring it into a real harness (alone, or alongside `interlock.git`), and
``docs/USAGE.md`` for every configuration knob and for authoring a new hook of this class.

This subpackage does not import :mod:`interlock.git`, and nothing in it requires
`interlock.git` to be installed, armed, or even present -- see ``README.md``'s section on
independent adoption.
"""
from __future__ import annotations
