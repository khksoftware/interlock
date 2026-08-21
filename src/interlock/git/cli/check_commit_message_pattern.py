# SPDX-License-Identifier: Apache-2.0
"""Refuse a commit whose message carries a trailer matching a forbidden pattern.

The CLI face of :mod:`interlock.git.commit_message_pattern`, and the only thing an
installed `commit-msg` shim for this gate calls. git hands a `commit-msg` hook exactly one
argument -- the path to the file holding the proposed message -- forwarded here as
``message_path``.

    <interpreter> -B -m interlock.git.cli.check_commit_message_pattern <message-file>
    <interpreter> -B -m interlock.git.cli.check_commit_message_pattern --install
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
from interlock.git.commit_message_pattern import (  # noqa: E402
    CLI_MODULE, GATE_LABEL, SPEC, staged_commit_message_pattern_failures_from_config,
)
from interlock.git.hookkit import is_armed  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("message_path", type=Path, nargs="?", default=None)
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

    if arguments.message_path is None:
        return report_gate_unavailable(
            GATE_LABEL, CLI_MODULE,
            "no commit-message file path was supplied (a commit-msg hook always passes one)",
        )

    try:
        failures = staged_commit_message_pattern_failures_from_config(
            arguments.message_path, repository_root=root, config_path=arguments.config_path,
        )
    except (GateError, ValueError, OSError) as error:
        return report_gate_unavailable(GATE_LABEL, CLI_MODULE, str(error))
    except Exception as error:  # noqa: BLE001
        return report_gate_unavailable(
            GATE_LABEL, CLI_MODULE, f"the message could not be checked ({type(error).__name__}: {error})"
        )

    if not failures:
        return EXIT_CLEAN
    print(f"{GATE_LABEL}: REFUSED. The commit message carries a forbidden trailer:", file=sys.stderr)
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
