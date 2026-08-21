# SPDX-License-Identifier: Apache-2.0
"""Shared, subject-agnostic git plumbing both host modules are built on.

Nothing in this module knows what a gate refuses or what a hook reminds about. It only
answers questions every gate or hook predicate needs answered the same way every time:
where is this working tree rooted, where do its hooks live, what is this commit actually
about to carry, and where does THIS worktree's own arming marker belong. Both
:mod:`interlock.git` and :mod:`interlock.turn` import from
here rather than re-deriving any of it -- a second, independently-maintained notion of
"how do I find the repository root" is exactly the kind of drift a consolidated framework
exists to close, and the fact that one of the two source packages this framework replaces
had its own, independently-written (and, per the module docstring below, subtly buggy)
copy of exactly that question is the concrete case in point.

## Why every subprocess call decodes bytes explicitly

Passing ``text=True`` to :func:`subprocess.run` decodes a child process's output using the
platform's default encoding -- on Windows, the ANSI codepage, not UTF-8. A caller that
hashes, compares, or pattern-matches that output can get a confident, wrong answer with
exit code 0: a byte a tool actually emitted is silently mangled or replaced, and nothing
raises. Every call here captures bytes and decodes as ``utf-8`` explicitly instead, so a
non-ASCII path, identity, or message round-trips correctly regardless of the host
platform's default. (The turn-boundary host's own predecessor package read its repository
root with ``subprocess.run(..., text=True)`` -- functionally harmless on an ASCII-only
path, but exactly the latent defect this module's convention exists to rule out
structurally rather than case by case. Consolidating onto one plumbing module fixes it in
the one place it needs fixing, rather than leaving two independently-drifting copies.)

## Why content is read from the index, never the working tree

A ``pre-commit`` hook runs after ``git add`` has already built the index but before the
commit object exists. Reading the working tree instead of the index would judge the wrong
thing on a partial (``git commit --only``/``-p``) commit, and -- more importantly -- would
refuse work that was already on its way to being fixed: a change staged, then corrected in
the working tree before committing, should be judged on what will actually be committed,
not on an already-superseded draft still sitting on disk. :func:`commit_paths` and
:func:`index_blob` therefore both read through git's own index-aware plumbing
(``diff --cached``, ``cat-file blob :<path>``), which automatically honours
``GIT_INDEX_FILE`` -- the temporary index git points a hook at for a ``--only`` partial
commit -- so a caller answers for exactly what this commit would carry, nothing else.

## `working_tree_root` versus `repository_root`

Two functions answer the same underlying question -- where is the repository this
process is being asked about -- with two different failure contracts, because the two
hosts have two different, deliberately stated failure biases (see ``README.md``'s design
principles for each). :func:`working_tree_root` RAISES :class:`~interlock.errors.GateError`
on failure, matching `interlock.git`'s fail-closed posture: a gate that cannot find the
repository it is judging has failed, and its caller decides to refuse. :func:`repository_root`
NEVER raises, returning ``None`` on any failure, matching `interlock.turn`'s fail-open
posture: a hook that cannot find the repository has nothing to check, not a fault to
propagate. Both call the identical subprocess plumbing underneath; only the error
handling differs, deliberately, at the boundary each host actually needs it at.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from interlock.errors import GateError


def run_git(root: str | Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    """Run ``git`` in ``root``, capturing bytes. Never ``text=True`` -- see module docstring."""
    return subprocess.run(
        ("git", *arguments), cwd=str(root), capture_output=True, check=False,
    )


def decode(payload: bytes) -> str:
    """Decode a git subprocess's stdout/stderr as UTF-8, explicitly, every time."""
    return payload.decode("utf-8")


def working_tree_root(start: str | Path) -> Path:
    """The top of the working tree ``start`` sits in. Raises :class:`GateError` on failure.

    A gate must judge the tree the action is happening in, which is not necessarily the
    tree the gate's own module was imported from -- they coincide in production but not
    under test, where a throwaway sandbox repository is judged by code imported from
    elsewhere on disk.
    """
    start = Path(start)
    result = run_git(start, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise GateError(
            f"{start} is not inside a git working tree: {decode(result.stderr).strip()}"
        )
    return Path(decode(result.stdout).strip()).resolve()


def repository_root(start: str | Path | None = None) -> Path | None:
    """The top of the working tree ``start`` (default: the current directory) sits in, or
    ``None`` on any failure. Never raises -- see module docstring on the two failure
    contracts.
    """
    try:
        result = run_git(Path(start) if start is not None else Path.cwd(), "rev-parse", "--show-toplevel")
    except Exception:
        return None
    if result.returncode != 0:
        return None
    try:
        root = Path(decode(result.stdout).strip())
    except Exception:
        return None
    return root if root.is_dir() else None


def worktree_git_dir(root: str | Path) -> Path:
    """This worktree's OWN git directory -- where its arming marker lives, not where hooks
    live.

    In a linked worktree these two directories differ (`git worktree add`): the git
    directory is per-worktree, but hooks resolve to the directory every worktree shares.
    See :func:`hooks_directory` and ``README.md``'s section on worktrees. Both hosts' own
    arming markers (see :mod:`interlock.arming`) live under this same directory,
    for the same worktree-scoping reason.
    """
    root = Path(root)
    result = run_git(root, "rev-parse", "--git-dir")
    if result.returncode != 0:
        raise GateError(
            f"{root} is not inside a git working tree: {decode(result.stderr).strip()}"
        )
    return (root / decode(result.stdout).strip()).resolve()


def hooks_directory(root: str | Path) -> Path:
    """Where git will actually look for a hook, honouring ``core.hooksPath`` if it is set.

    When ``core.hooksPath`` is unset, this resolves through ``git rev-parse
    --git-common-dir`` -- the directory EVERY linked worktree of a repository shares, not
    the per-worktree one :func:`worktree_git_dir` returns. That distinction is the whole
    reason `interlock.git` arms per worktree but installs its hook shim once: see
    ``docs/INTEGRATION.md``. `interlock.turn` has no shim and does not call this function --
    its own hooks are invoked directly by the harness per its own hook configuration, not
    dispatched through a shared, single-file-per-event directory the way git hooks are.
    """
    root = Path(root)
    configured = run_git(root, "config", "--get", "core.hooksPath")
    if configured.returncode == 0 and decode(configured.stdout).strip():
        return (root / decode(configured.stdout).strip()).resolve()
    common = run_git(root, "rev-parse", "--git-common-dir")
    if common.returncode != 0:
        raise GateError(
            f"the git common directory is unreadable: {decode(common.stderr).strip()}"
        )
    return (root / decode(common.stdout).strip()).resolve() / "hooks"


def commit_paths(root: str | Path) -> tuple[str, ...]:
    """Every path whose content this commit changes, as git has already prepared it.

    Reads the INDEX git handed the hook (honouring ``GIT_INDEX_FILE``, which git sets to a
    temporary index for a ``--only``/partial commit) -- never the working tree, never a
    repository-wide walk. A root commit (no HEAD yet) treats every cached path as an
    addition.
    """
    root = Path(root)
    if run_git(root, "rev-parse", "--verify", "--quiet", "HEAD").returncode == 0:
        result = run_git(root, "diff", "--cached", "--name-only", "-z", "HEAD")
    else:
        result = run_git(root, "ls-files", "--cached", "-z")
    if result.returncode != 0:
        raise GateError(
            "this commit's changed-path set is unreadable, so the gate cannot judge it: "
            f"{decode(result.stderr).strip()}"
        )
    return tuple(name for name in decode(result.stdout).split("\0") if name)


def index_blob(root: str | Path, path: str) -> str | None:
    """The content this commit will carry for ``path``, or ``None`` if it carries none.

    ``git cat-file blob :<path>`` is plumbing over the index git handed the hook -- not a
    working-tree read, and not ``git show`` (which would apply a textconv filter). May
    raise :class:`UnicodeDecodeError` for an undecodable (e.g. binary) blob; callers treat
    that as "nothing to scan."
    """
    result = run_git(Path(root), "cat-file", "blob", f":{path}")
    if result.returncode != 0:
        return None
    return decode(result.stdout)


def effective_git_config(root: str | Path, key: str) -> str | None:
    """The value ``git`` would actually use for ``key`` right now (local overriding
    global), exactly as ``git config --get`` resolves precedence. ``None`` if unset."""
    result = run_git(Path(root), "config", "--get", key)
    if result.returncode != 0:
        return None
    value = decode(result.stdout).strip()
    return value or None


__all__ = (
    "commit_paths", "decode", "effective_git_config", "hooks_directory", "index_blob",
    "repository_root", "run_git", "working_tree_root", "worktree_git_dir",
)
