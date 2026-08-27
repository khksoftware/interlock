# SPDX-License-Identifier: Apache-2.0
"""``interlock.guard`` -- refusals that fire **before a command executes**, the third
boundary this distribution covers alongside :mod:`interlock.git` (a git action) and
:mod:`interlock.turn` (an agent turn). See ``README.md`` at the root of this distribution
for what the three hosts share and ``docs/INTEGRATION.md`` for installing this one alone or
alongside the other two -- this subpackage imports neither of them, and neither requires
this one's configuration, state, or install step to function.
"""
from __future__ import annotations
