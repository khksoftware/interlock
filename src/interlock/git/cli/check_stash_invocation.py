# SPDX-License-Identifier: Apache-2.0
"""Refuse a `git stash` invocation, at the `reference-transaction` hook.

The CLI face of :mod:`interlock.git.stash_invocation`, and the only thing an installed
`reference-transaction` shim for this gate calls. git invokes this hook as
``reference-transaction <phase>`` with the batch of ref updates on stdin -- both are read
here, never assumed.

    <interpreter> -B -m interlock.git.cli.check_stash_invocation prepared < updates
    <interpreter> -B -m interlock.git.cli.check_stash_invocation --install

**Never called against this package's own distribution automatically** -- installing a
`reference-transaction` hook affects every worktree of whatever repository it is installed
into, which is a decision for the adopter to make explicitly. See ``docs/INTEGRATION.md``.
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
from interlock.git.stash_invocation import (  # noqa: E402
    CLI_MODULE, GATE_LABEL, SPEC, stash_invocation_refusal,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", nargs="?", default=None, help="prepared, committed, or aborted")
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

    if arguments.phase is None:
        return report_gate_unavailable(
            GATE_LABEL, CLI_MODULE,
            "no transaction phase was supplied (a reference-transaction hook always passes one)",
        )

    transaction_stdin = sys.stdin.read()
    refusal = stash_invocation_refusal(arguments.phase, transaction_stdin)
    if refusal is None:
        return EXIT_CLEAN
    print(f"{GATE_LABEL}: REFUSED. {refusal}", file=sys.stderr)
    if not is_armed(root, SPEC):
        print(
            "\nNote: this worktree is NOT armed, so no transaction here is actually gated. "
            "Arm it with --install.",
            file=sys.stderr,
        )
    return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
