# SPDX-License-Identifier: Apache-2.0
"""Per-gate CLI wrappers -- the shim's own `exec` target, one module per gate.

Not a public API this package promises to keep stable across every minor release -- see
`_shared.py`'s own docstring. An adopter driving a gate directly (to check without a real
commit, or to arm without installing) uses the unified `interlock` command
(``interlock install|arm|disarm|status``, see ``docs/INTEGRATION.md``); these modules
exist because git's own hook mechanism needs a concrete, importable command to `exec`, and
that command has to be one specific module per gate rather than a dispatched subcommand
(the shim is a fixed, byte-frozen constant -- it cannot itself parse an evolving CLI
surface).
"""
from __future__ import annotations
