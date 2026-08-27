# SPDX-License-Identifier: Apache-2.0
"""Verify a DEPLOYED copy of a hook or gate against its own tracked source, on any host.

## The gap this closes

`interlock.git`'s installer writes a fixed, byte-frozen shell shim holding no logic at all
-- everything a gate could get wrong lives in the tracked Python module the shim `exec`s,
and `interlock.git.hookkit.installation_state` already compares the deployed shim against
the exact bytes `render_shim` would produce. That comparison is effectively free: the shim
is generated content this package itself writes and can re-derive at any time.

`interlock.turn` and `interlock.guard` have no shim. Their own hooks are ordinarily
invoked directly out of the installed package (`python -m interlock.turn.role_label`), in
which case there is only ever one copy of the code and nothing can drift. But an adopter
whose harness cannot invoke a package module that way -- or whose own deployment
convention copies a hook's file into a per-user, per-harness hooks directory rather than
importing it live -- ends up with a second, independent copy of that hook's source with no
built-in relationship to the one this package ships. Nothing compares them, and a stale
deployed copy silently keeps running whatever it last was after the installed package
moves on. This module is that comparison, generalized across every host this distribution
ships, so an adopter who deploys this way is not left to remember a manual `diff` -- the
same shape "remember to run it" reliably fails in practice on any adopter's own machine,
not only in this package's development history.

## Two comparison bases, because the two sides are not shaped alike

* **A git gate's deployed artifact is its rendered SHIM** (see
  :mod:`interlock.git.hookkit`) -- :func:`deployed_shim_drift` compares deployed bytes
  against the exact shim text `GateSpec.shim` already carries.
* **A turn or guard hook's deployed artifact, when copied rather than imported, is the
  hook MODULE'S OWN SOURCE FILE** -- :func:`deployed_copy_drift` resolves that file via
  ``importlib`` (so it always compares against whatever is actually installed and
  importable right now, never a guessed path) and compares it byte for byte against the
  deployed copy.

Both directions report a finding as a string, or ``None`` for a clean comparison -- never
raise on ordinary drift, so a caller can check many ids in one pass and report every
finding rather than stopping at the first. Both DO raise if the id itself cannot be
resolved at all (an unknown module, a module with no ``__file__``) -- that is a caller
error, not a drift finding, and silently returning "no finding" for it would misreport an
unresolvable check as a clean one.
"""
from __future__ import annotations

import hashlib
import importlib
from pathlib import Path


def sha256_of(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolve_module_source(module_name: str) -> Path:
    """Import ``module_name`` and return the path to its own tracked ``.py`` source file.

    Raises (``ModuleNotFoundError``, or ``ValueError`` for a module with no ``__file__``,
    e.g. a namespace package) rather than returning a sentinel -- an unresolvable module is
    a caller error to surface, not a drift finding to report quietly as "no difference
    found."
    """
    module = importlib.import_module(module_name)
    origin = getattr(module, "__file__", None)
    if not origin:
        raise ValueError(f"{module_name} has no __file__ -- not resolvable as a pinned source")
    return Path(origin)


def deployed_copy_drift(deployed_path: str | Path, module_name: str) -> str | None:
    """One finding if the deployed copy at ``deployed_path`` does not byte-for-byte match
    ``module_name``'s own installed source, else ``None``.

    A missing ``deployed_path`` is itself a finding -- "nothing to check drift against" is
    not the same fact as "checked and found no drift," and collapsing the two is exactly
    the shape that lets an unpoliced state read as a policed one.
    """
    deployed = Path(deployed_path)
    if not deployed.is_file():
        return f"{module_name}: no deployed copy at {deployed_path}"
    tracked = resolve_module_source(module_name)
    tracked_hash = sha256_of(tracked)
    deployed_hash = sha256_of(deployed)
    if tracked_hash != deployed_hash:
        return (
            f"{module_name}: deployed copy at {deployed_path} (sha256 {deployed_hash}) "
            f"differs from installed source at {tracked} (sha256 {tracked_hash})"
        )
    return None


def deployed_shim_drift(deployed_path: str | Path, expected_shim: str) -> str | None:
    """One finding if the deployed git-hook shim at ``deployed_path`` does not match
    ``expected_shim`` (a ``GateSpec.shim``, or the composed dispatcher constant) byte for
    byte, else ``None``. The same comparison
    :func:`interlock.git.hookkit.installation_state` already performs internally, exposed
    here as its own callable so it can be driven by id, uniformly with the other two
    hosts, from one CLI verb.
    """
    deployed = Path(deployed_path)
    if not deployed.is_file():
        return f"no deployed shim at {deployed_path}"
    existing = deployed.read_bytes().decode("utf-8", errors="replace")
    if existing != expected_shim:
        return f"deployed shim at {deployed_path} does not match the expected rendered shim"
    return None


__all__ = (
    "deployed_copy_drift", "deployed_shim_drift", "resolve_module_source", "sha256_of",
)
