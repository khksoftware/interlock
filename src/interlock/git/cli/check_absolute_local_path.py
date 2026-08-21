# SPDX-License-Identifier: Apache-2.0
"""Refuse a commit whose staged content embeds an absolute local filesystem path.

The CLI face of :mod:`interlock.git.absolute_local_path`.

    <interpreter> -B -m interlock.git.cli.check_absolute_local_path
    <interpreter> -B -m interlock.git.cli.check_absolute_local_path --install
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from interlock.errors import GateError  # noqa: E402
from interlock.git.absolute_local_path import (  # noqa: E402
    CLI_MODULE, GATE_LABEL, SPEC, staged_absolute_local_path_failures_from_config,
)
from interlock.git.cli._shared import (  # noqa: E402
    EXIT_CLEAN, EXIT_REFUSED, report_gate_unavailable, resolve_root, run_install,
)
from interlock.git.hookkit import is_armed  # noqa: E402


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
        failures = staged_absolute_local_path_failures_from_config(
            root, config_path=arguments.config_path
        )
    except (GateError, ValueError) as error:
        return report_gate_unavailable(GATE_LABEL, CLI_MODULE, str(error))
    except Exception as error:  # noqa: BLE001
        return report_gate_unavailable(
            GATE_LABEL, CLI_MODULE, f"the commit could not be checked ({type(error).__name__}: {error})"
        )

    if not failures:
        return EXIT_CLEAN
    print(
        f"{GATE_LABEL}: REFUSED. What this commit would carry embeds an absolute local "
        "filesystem path:",
        file=sys.stderr,
    )
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)
    print(
        "\nRedact the path before committing. A genuine illustrative or provenance citation "
        "can be exempted via interlock.json's absolute_local_path.citations / "
        ".deferred_scope -- see docs/USAGE.md.",
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
