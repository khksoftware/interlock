# SPDX-License-Identifier: Apache-2.0
"""Refuse a commit whose staged content touches a registered protected path.

The CLI face of :mod:`interlock.git.protected_paths`, and the only thing an installed
`pre-commit` shim for this gate calls.

    <interpreter> -B -m interlock.git.cli.check_protected_paths
    <interpreter> -B -m interlock.git.cli.check_protected_paths --install

Reads its protected-path registry from ``interlock.json`` (see ``docs/USAGE.md``/
``docs/INTEGRATION.md``); a repository with no such file, or no ``protected_paths``
section in it, protects nothing -- this gate has no opinion of its own about what matters
in a repository it has never seen.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from interlock.config import load_config, section  # noqa: E402
from interlock.errors import GateError  # noqa: E402
from interlock.git.cli._shared import (  # noqa: E402
    EXIT_CLEAN, EXIT_REFUSED, report_gate_unavailable, resolve_root, run_install,
)
from interlock.git.hookkit import is_armed  # noqa: E402
from interlock.git.protected_paths import (  # noqa: E402
    CLI_MODULE, GATE_LABEL, SPEC, protected_path_failures,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=None, dest="config_path")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--interpreter", type=Path, default=Path(sys.executable))
    arguments = parser.parse_args(argv)

    try:
        root = resolve_root(arguments.repository_root)
    except GateError as error:
        return report_gate_unavailable(GATE_LABEL, CLI_MODULE, str(error))

    if arguments.install:
        return run_install(root, SPEC, arguments.interpreter, GATE_LABEL)

    try:
        config = section(load_config(root, path=arguments.config_path), "protected_paths")
        failures = protected_path_failures(
            root,
            protected_paths=tuple(config.get("paths", ())),
            protected_prefixes=tuple(config.get("prefixes", ())),
        )
    except (GateError, ValueError) as error:
        return report_gate_unavailable(GATE_LABEL, CLI_MODULE, str(error))
    except Exception as error:  # noqa: BLE001
        return report_gate_unavailable(
            GATE_LABEL, CLI_MODULE, f"the commit could not be checked ({type(error).__name__}: {error})"
        )

    if not failures:
        return EXIT_CLEAN
    print(f"{GATE_LABEL}: REFUSED. This commit touches a registered protected path:", file=sys.stderr)
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)
    print(
        "\nIf this change is authorized, use the disclosed bypass (`git commit --no-verify`) "
        "and say so in your report -- nothing mechanical here can observe that you did.",
        file=sys.stderr,
    )
    if not is_armed(root, SPEC):
        print(
            "\nNote: this worktree is NOT armed, so no commit here is actually gated. Arm it "
            "with --install.",
            file=sys.stderr,
        )
    return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
