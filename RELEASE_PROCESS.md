# Release process

## Distribution name — unconfirmed, and deliberately isolated to one field

**The PyPI-facing distribution name `interlock` in `pyproject.toml`'s `[project] name`
has not been checked against any public package index.** "Interlock" is a common enough
word that it may already be taken. This was deliberately NOT queried against any external
service while building this package. Check availability before the first real publish,
and if it is taken, change **only** `pyproject.toml`'s `name` field — it is the single
place that string is declared, precisely so this is a one-line change rather than a
scattered rename. The import package (`import interlock`), the CLI command
(`interlock ...`), the module paths (`interlock.git`, `interlock.turn`), and every doc in
this distribution stay `interlock` regardless of what the distribution name on an index
ends up being; only `[project] name` and, if you care about the URL matching, the
`Homepage` field need to change.

## Version declaration

The single source of truth is `__version__` in `src/interlock/__init__.py`.
`pyproject.toml` reads it dynamically (`[tool.setuptools.dynamic] version = { attr =
"interlock.__version__" }`) rather than restating it — a version number kept in two
places is a version number that drifts. Nowhere else in this distribution states a
version number as a literal; if you find one, that is a bug, not a second source of
truth.

## What counts as breaking, for THIS package specifically

Ordinary semver treats a public function's signature as the API surface. That is
necessary but not sufficient here, because this package's product is partly a set of
*refusals and reminders*, and their behaviour is as much the contract as any function
signature:

- **MAJOR**: a change that makes a previously-passing git action, or a previously-silent
  turn, now refused or escalated by default; a breaking change to a public function's
  signature; a change to `GateSpec.marker_name`/`hook_name` (silently disarms every
  existing git-side installation); a change to any key in
  `interlock.turn.arming.HOOK_MARKER_NAMES` (silently disarms every existing turn-side
  installation — the identical concern, now on both hosts); a rename of any environment
  variable in `interlock.turn.config`; or a change to a hook's stdin/stdout contract.
- **MINOR**: a new gate, a new hook, a new optional configuration key with a
  backward-compatible default, or a new public helper that does not change any existing
  check's behaviour.
- **PATCH**: a documentation fix, an internal refactor with no behavioural or API change,
  or a bug fix that makes an ALREADY-INTENDED refusal or reminder actually fire (the bug
  was the check being less strict than its own documentation claimed) — say so explicitly
  in the changelog entry so an adopter reading only the version number is not misled into
  thinking nothing behavioural changed.

## Marker names and environment-variable names are part of the compatibility contract, on BOTH hosts now

Every existing arming marker on every adopter's machine is a file named after either a
`GateSpec.marker_name` (git side) or an entry in
`interlock.turn.arming.HOOK_MARKER_NAMES` (turn side), sitting inside that worktree's own
git directory. Renaming either is not an internal refactor — it silently disarms every
worktree already armed under the old name, with no error and no signal that anything
changed. Treat every marker name, and every `INTERLOCK_*` environment variable name in
`interlock.turn.config`, as append-only and immutable for the lifetime of a gate or hook.
If one genuinely must change, that is a MAJOR release, and the changelog entry must say
explicitly: "worktrees armed under the old marker name are now silently unarmed; re-run
`interlock arm <id>` after upgrading" (or the equivalent for an environment-variable
rename).

## Before cutting a release

1. **The full test suite is green**, run from this distribution's own root, with the
   system interpreter you intend adopters to use (never a stale or unrelated virtual
   environment): `python -m pytest -p no:cacheprovider tests`.
2. **Grep this distribution for anything that should not be here.** No path specific to
   the machine or project this package was developed against, no identifier naming that
   project's own internal tracking, no vendor/harness name presented as though this
   package were exclusive to it. This is a pre-release check performed every time, because
   a later contribution can reintroduce exactly this.
3. **The coverage figures and residue-class sections in `README.md` still read as
   honest**, for BOTH hosts. If a new gate or hook closes a former "permanently
   unreachable" case, or a known reliability gap is closed elsewhere, update the figure —
   do not let it go stale in the direction that flatters this package.
4. **`tests/test_module_independence.py` still passes.** A change that makes
   `interlock.git` or `interlock.turn` import the other, or depend on the other's
   configuration to function, is a regression on the independent-adoption claim this
   package makes, even if every other test is green.
5. **`CHANGELOG.md` has an entry**, under the discipline above, before the version bump —
   not after.

## Cutting the release

1. Bump `__version__` in `src/interlock/__init__.py`.
2. Move the `[Unreleased]` section of `CHANGELOG.md` to a new dated, versioned heading;
   leave a fresh empty `[Unreleased]` section above it.
3. Commit both together, tag the commit `vX.Y.Z`, and push the tag along with the branch.
4. Build and publish, if you publish to an index: confirm the distribution name (see the
   top of this document) first, then `python -m build`, then upload the resulting `dist/`
   artifacts with your chosen tool. This distribution ships no CI/publish workflow
   itself — wire that into whatever automation the repository this package lives in
   already uses, rather than this package assuming a specific CI provider on your behalf.
