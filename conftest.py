# SPDX-License-Identifier: Apache-2.0
"""Makes the package importable for the test suite without an install step.

Runs from the exported folder: `python -m pytest tests` (or `pytest interlock` from one
level up) picks this up automatically because pytest loads every `conftest.py` between
its rootdir and the collected test files.

Also exports `PYTHONPATH=<src>` into this process's own environment, not only `sys.path`.
Several tests in `tests/git/test_*.py` install a real hook shim and drive a REAL
`git commit` (or `git stash`) against it -- the hook `exec`s a fresh Python interpreter as
a genuinely separate OS process, which does not inherit this process's `sys.path`, only
its environment. Setting `PYTHONPATH` here is what lets that child process
`import interlock` without requiring this package to be `pip install`-ed first, so the
test suite proves the exported copy works standing alone, with nothing beyond a Python
interpreter and git. A real adopter would normally `pip install` this package instead
(see docs/INTEGRATION.md); this is the zero-install path this test suite itself relies on.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
for entry in (SRC, ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

_existing_pythonpath = os.environ.get("PYTHONPATH", "")
_entries = [str(SRC)] + ([_existing_pythonpath] if _existing_pythonpath else [])
os.environ["PYTHONPATH"] = os.pathsep.join(_entries)
