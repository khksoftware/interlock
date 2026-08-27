# SPDX-License-Identifier: Apache-2.0
"""Tests for :mod:`interlock.deployment_pinning` -- verifying a DEPLOYED standalone copy
of a gate or hook against its own tracked source, for the case where an adopter's harness
or deployment convention copies a file rather than importing the installed package live.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from interlock import deployment_pinning, registry
from interlock.turn import role_label as role_label_module


class TestResolveModuleSource:
    def test_resolves_a_real_installed_module(self) -> None:
        resolved = deployment_pinning.resolve_module_source("interlock.turn.role_label")
        assert resolved == Path(role_label_module.__file__)
        assert resolved.is_file()

    def test_an_unknown_module_raises(self) -> None:
        with pytest.raises(ModuleNotFoundError):
            deployment_pinning.resolve_module_source("interlock.does_not_exist_at_all")


class TestDeployedCopyDrift:
    def test_a_missing_deployed_copy_is_a_finding(self, tmp_path: Path) -> None:
        missing = tmp_path / "role_label.py"
        finding = deployment_pinning.deployed_copy_drift(missing, "interlock.turn.role_label")
        assert finding is not None
        assert "no deployed copy" in finding

    def test_an_identical_deployed_copy_is_clean(self, tmp_path: Path) -> None:
        tracked = deployment_pinning.resolve_module_source("interlock.turn.role_label")
        deployed = tmp_path / "role_label.py"
        deployed.write_bytes(tracked.read_bytes())
        assert deployment_pinning.deployed_copy_drift(deployed, "interlock.turn.role_label") is None

    def test_a_differing_deployed_copy_is_a_finding_naming_both_hashes(self, tmp_path: Path) -> None:
        deployed = tmp_path / "role_label.py"
        deployed.write_text("# a stale, hand-edited copy\n", encoding="utf-8")
        finding = deployment_pinning.deployed_copy_drift(deployed, "interlock.turn.role_label")
        assert finding is not None
        assert "differs from installed source" in finding
        assert "sha256" in finding


class TestDeployedShimDrift:
    def test_a_missing_deployed_shim_is_a_finding(self, tmp_path: Path) -> None:
        missing = tmp_path / "pre-commit"
        finding = deployment_pinning.deployed_shim_drift(missing, "expected shim text\n")
        assert finding is not None
        assert "no deployed shim" in finding

    def test_an_identical_deployed_shim_is_clean(self, tmp_path: Path) -> None:
        shim_text = "#!/bin/sh\nexit 0\n"
        deployed = tmp_path / "pre-commit"
        deployed.write_text(shim_text, encoding="utf-8", newline="")
        assert deployment_pinning.deployed_shim_drift(deployed, shim_text) is None

    def test_a_differing_deployed_shim_is_a_finding(self, tmp_path: Path) -> None:
        deployed = tmp_path / "pre-commit"
        deployed.write_text("#!/bin/sh\n# hand-edited\nexit 0\n", encoding="utf-8", newline="")
        finding = deployment_pinning.deployed_shim_drift(deployed, "#!/bin/sh\nexit 0\n")
        assert finding is not None
        assert "does not match" in finding

    def test_matches_the_real_gate_spec_shim_used_by_the_registry(self, tmp_path: Path) -> None:
        """The comparison basis is the exact same GateSpec.shim installation_state already
        checks internally -- proven against a real registry entry, not a hand-built fixture."""
        gate = registry.find_git_gate("git.protected-paths")
        assert gate is not None
        deployed = tmp_path / "pre-commit"
        deployed.write_text(gate.spec.shim, encoding="utf-8", newline="")
        assert deployment_pinning.deployed_shim_drift(deployed, gate.spec.shim) is None
