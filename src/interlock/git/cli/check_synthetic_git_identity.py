# SPDX-License-Identifier: Apache-2.0
"""Refuse a commit made under a synthetic (reserved-domain) git identity.

The CLI face of :mod:`interlock.git.synthetic_git_identity`.

    <interpreter> -B -m interlock.git.cli.check_synthetic_git_identity
    <interpreter> -B -m interlock.git.cli.check_synthetic_git_identity --install
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from interlock.errors import GateError  # noqa: E402
from interlock.git.cli._shared import (  # noqa: E402
    EXIT_CLEAN, EXIT_REFUSED, report_gate_unavailable, resolve_root, run_install,
)
from interlock.git.hookkit import is_armed  # noqa: E402
from interlock.git.synthetic_git_identity import (  # noqa: E402
    CLI_MODULE, GATE_LABEL, SPEC, synthetic_identity_failures,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=None)
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
        failures = synthetic_identity_failures(root)
    except GateError as error:
        return report_gate_unavailable(GATE_LABEL, CLI_MODULE, str(error))
    except Exception as error:  # noqa: BLE001
        return report_gate_unavailable(
            GATE_LABEL, CLI_MODULE, f"the commit could not be checked ({type(error).__name__}: {error})"
        )

    if not failures:
        return EXIT_CLEAN
    print(f"{GATE_LABEL}: REFUSED. The configured commit identity looks synthetic:", file=sys.stderr)
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)
    if not is_armed(root, SPEC):
        print(
            "\nNote: this worktree is NOT armed, so no commit here is actually gated. Arm it "
            "with --install.",
            file=sys.stderr,
        )
    return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
