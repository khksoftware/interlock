# SPDX-License-Identifier: Apache-2.0
"""Every adopter-specific knob :mod:`interlock.guard.execution_guard` reads, in one place,
with its default.

**Environment-variable-primary, exactly like `interlock.turn`'s own configuration, and for
the identical reason.** This hook is invoked by the harness as a subprocess at a
``PreToolUse``-shaped boundary, and the one thing every harness reliably lets an adopter
control at that point is the subprocess's own environment -- not a bespoke config-path
convention this package would have to teach every harness about. See
:mod:`interlock.turn.config`'s own module docstring for the fuller argument; it applies here
unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- approval state -------------------------------------------------------------------
#
# Where a recorded, expiring, one-shot approval receipt is kept between the moment a user
# authorizes a specific blocked command and the moment that exact command is retried. See
# `execution_guard.py` for the full approval lifecycle.
#
# Deliberately a FUNCTION reading the environment fresh on every call, not a module-level
# constant frozen at import time: a caller (this package's own test suite included) that
# records an approval directly, in-process, and then drives the real hook as a separate
# subprocess needs both to resolve the SAME state directory from the SAME environment
# variable read at the moment each one actually runs -- a constant computed once at import
# would freeze whatever the variable held before the test ever set it.
def state_root() -> Path:
    return Path(
        os.environ.get("INTERLOCK_GUARD_STATE_DIR", str(Path.home() / ".interlock" / "guard"))
    )


def default_approval_expiry_minutes() -> int:
    """How long a recorded approval remains usable before it expires, in minutes, unless
    the caller overrides it explicitly when recording one. Read fresh each call, for the
    same reason :func:`state_root` is -- see that function's docstring."""
    return int(os.environ.get("INTERLOCK_GUARD_DEFAULT_APPROVAL_EXPIRY_MINUTES", "30"))


__all__ = ("default_approval_expiry_minutes", "state_root")
