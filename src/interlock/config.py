# SPDX-License-Identifier: Apache-2.0
"""The one configuration file and discovery mechanism both host modules read from.

One small, tracked JSON file at the root of the repository being protected --
``interlock.json`` -- holds one top-level section per adopter-specific setting
either host needs. Track it, it is ordinary project content, not a secret and not
machine-specific.

**Every section is independent, and reading one never requires another to exist.** A
repository adopting only `interlock.git` needs no `interlock.turn` section in this file, and vice
versa -- see ``README.md``'s section on independent adoption. A missing file, or a file
missing the section a given gate or hook reads, means "use that gate's or hook's own
built-in default," exactly as it did before consolidation; nothing here requires an
adopter using one host to know the other host's configuration shape exists.

`interlock.git`'s gates read their own section directly through :func:`load_config` /
:func:`section`, exactly as the equivalent gates did in ``action-boundary-gates``, one of
the two standalone exports this framework replaces -- `interlock.json`'s
``protected_paths`` / ``absolute_local_path`` / ``commit_message_pattern`` keys are
unchanged in shape from that package's own ``action-boundary-gates.json``; only the
filename changed. `interlock.turn`'s settings are
primarily environment-variable-driven (a hook subprocess's environment is what an AI
coding harness actually lets an adopter configure at hook-invocation time; see
`interlock.turn.config`'s own docstring for why that stays the PRIMARY mechanism rather than
being replaced), but every setting there also accepts a same-named key in a
``"turn"`` section of this identical file as a second, lower-priority layer beneath
the environment-variable override and above the built-in default -- one file, one
discovery routine, for both hosts, without forcing either host to adopt the other's
historical configuration convention wholesale.

Nothing in either host REQUIRES this file to be named or placed exactly this way -- every
git-host predicate function also accepts its configuration directly as arguments, for a
caller (a test, or a project with its own configuration convention) that wants to supply
it another way, and every `interlock.turn` setting is a plain module-level constant a caller
can monkeypatch or an adopter can override entirely via environment variable. The file is
only the default discovery path.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Where both hosts look for configuration by default, relative to the repository root.
DEFAULT_CONFIG_FILENAME = "interlock.json"


def config_path(repository_root: str | Path, *, path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    return Path(repository_root) / DEFAULT_CONFIG_FILENAME


def load_config(repository_root: str | Path, *, path: str | Path | None = None) -> dict[str, Any]:
    """The whole configuration file, parsed, or ``{}`` if it does not exist.

    A missing file is not an error -- it means "use each gate's or hook's own built-in
    default," which every reader of this documents explicitly for itself. A file that
    exists but is not valid JSON IS an error: silently ignoring malformed configuration
    would make a gate less strict than an adopter believes it configured it to be, which
    is the wrong direction for a fail-closed mechanism to fail in. (`interlock.turn`'s own
    fail-open readers of this same file choose differently, and say so where they do --
    see `interlock.turn.config`.)
    """
    resolved = config_path(repository_root, path=path)
    if not resolved.is_file():
        return {}
    try:
        parsed = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{resolved} exists but is not valid JSON ({error}); fix or remove it -- a "
            "gate reading it treats malformed configuration as a reason to refuse, not as "
            "an empty configuration."
        ) from error
    if not isinstance(parsed, dict):
        raise ValueError(f"{resolved} must contain a JSON object at the top level")
    return parsed


def section(config: dict[str, Any], name: str) -> dict[str, Any]:
    """One gate's or hook's own slice of the whole config file, or ``{}`` if it named no
    section."""
    value = config.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"config section {name!r} must be a JSON object, got {type(value).__name__}")
    return value


__all__ = ("DEFAULT_CONFIG_FILENAME", "config_path", "load_config", "section")
