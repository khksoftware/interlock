# SPDX-License-Identifier: Apache-2.0
"""Enables ``python -m interlock ...`` as an alternative to the ``interlock`` console
script (useful before the distribution is installed with an entry point on `PATH`, e.g.
via `PYTHONPATH=src python -m interlock status`)."""
from __future__ import annotations

from interlock.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
