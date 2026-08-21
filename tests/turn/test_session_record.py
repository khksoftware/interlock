# SPDX-License-Identifier: Apache-2.0
"""Tests for `interlock.turn.session_record`, the shared reader both roster hooks depend
on."""
from __future__ import annotations

import json

from interlock.turn import session_record as sr


class TestPlatformNode:
    def test_multi_platform_document_finds_named_platform(self):
        document = {"platforms": [{"platform": "codex", "roster": {}}, {"platform": "claude", "roster": {"x": 1}}]}
        node = sr.platform_node(document, platform="claude")
        assert node == {"platform": "claude", "roster": {"x": 1}}

    def test_multi_platform_document_with_no_platform_argument_returns_first(self):
        document = {"platforms": [{"platform": "codex", "roster": {"x": 1}}]}
        node = sr.platform_node(document)
        assert node["platform"] == "codex"

    def test_missing_platform_name_returns_none(self):
        document = {"platforms": [{"platform": "codex"}]}
        assert sr.platform_node(document, platform="claude") is None

    def test_single_platform_document_falls_back_to_top_level(self):
        document = {"roster": {"state": "none", "entries": []}, "queue": []}
        assert sr.platform_node(document) is document

    def test_document_with_neither_shape_returns_none(self):
        assert sr.platform_node({"unrelated": True}) is None


class TestRosterIsEmpty:
    def test_verified_empty(self):
        assert sr.roster_is_empty({"roster": {"state": "none", "entries": []}}) is True

    def test_not_observable_is_not_empty(self):
        assert sr.roster_is_empty({"roster": {"state": "not-observable", "entries": []}}) is False

    def test_enumerated_with_entries_is_not_empty(self):
        assert sr.roster_is_empty({"roster": {"state": "enumerated", "entries": [{"id": "a"}]}}) is False

    def test_missing_roster_is_not_empty(self):
        assert sr.roster_is_empty({}) is False


class TestDispatchableRows:
    def _node(self, queue):
        return {"queue": queue}

    def test_queued_sequenced_unblocked_row_is_dispatchable(self):
        node = self._node([{"id": "PROJ-1", "status": "queued", "sequenced": True}])
        assert sr.dispatchable_rows(node) == ["PROJ-1"]

    def test_non_queued_status_excluded(self):
        node = self._node([{"id": "PROJ-1", "status": "in-progress", "sequenced": True}])
        assert sr.dispatchable_rows(node) == []

    def test_unsequenced_row_excluded(self):
        node = self._node([{"id": "PROJ-1", "status": "queued", "sequenced": False}])
        assert sr.dispatchable_rows(node) == []

    def test_blocked_row_excluded(self):
        node = self._node([{"id": "PROJ-1", "status": "queued", "sequenced": True, "blocked_on": "PROJ-0"}])
        assert sr.dispatchable_rows(node) == []

    def test_exempted_row_excluded(self):
        node = self._node([{"id": "PROJ-1", "status": "queued", "sequenced": True}])
        assert sr.dispatchable_rows(node, exemptions={"PROJ-1": "reason"}) == []

    def test_backtick_wrapped_id_is_stripped(self):
        node = self._node([{"id": "`PROJ-1`", "status": "queued", "sequenced": True}])
        assert sr.dispatchable_rows(node) == ["PROJ-1"]

    def test_malformed_rows_never_raise(self):
        node = {"queue": [None, "not-a-dict", {"status": "queued"}]}
        assert sr.dispatchable_rows(node) == []


class TestRegisterIds:
    def test_returns_upper_cased_ids(self):
        node = {"roster": {"entries": [{"id": "proj-1"}, {"id": "PROJ-2"}]}}
        assert sr.register_ids(node) == ("PROJ-1", "PROJ-2")

    def test_missing_roster_returns_empty(self):
        assert sr.register_ids({}) == ()


class TestRegisterState:
    def test_reads_state(self):
        assert sr.register_state({"roster": {"state": "enumerated"}}) == "enumerated"

    def test_missing_roster_returns_none(self):
        assert sr.register_state({}) is None


class TestLoadRecord:
    def test_valid_json_object(self, tmp_path):
        path = tmp_path / "record.json"
        path.write_text(json.dumps({"queue": []}), encoding="utf-8")
        assert sr.load_record(path) == {"queue": []}

    def test_missing_file_returns_none(self, tmp_path):
        assert sr.load_record(tmp_path / "missing.json") is None

    def test_malformed_json_returns_none(self, tmp_path):
        path = tmp_path / "record.json"
        path.write_text("not json", encoding="utf-8")
        assert sr.load_record(path) is None

    def test_json_array_is_not_a_valid_record(self, tmp_path):
        path = tmp_path / "record.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        assert sr.load_record(path) is None


class TestQuiescingCommand:
    def _write(self, tmp_path, lines):
        path = tmp_path / "t.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for entry in lines:
                handle.write(json.dumps(entry) + "\n")
        return str(path)

    def test_command_name_is_detected(self, tmp_path):
        path = self._write(tmp_path, [{"isSidechain": False, "message": "<command-name>/wrap-up</command-name>"}])
        assert sr.a_quiescing_command_is_running(path, ("wrap-up",)) is True

    def test_no_marker_is_not_detected(self, tmp_path):
        path = self._write(tmp_path, [{"isSidechain": False, "message": "just talking"}])
        assert sr.a_quiescing_command_is_running(path, ("wrap-up",)) is False

    def test_sidechain_entry_excluded(self, tmp_path):
        path = self._write(tmp_path, [{"isSidechain": True, "message": "<command-name>/wrap-up</command-name>"}])
        assert sr.a_quiescing_command_is_running(path, ("wrap-up",)) is False

    def test_empty_command_list_never_detects(self, tmp_path):
        path = self._write(tmp_path, [{"isSidechain": False, "message": "<command-name>/wrap-up</command-name>"}])
        assert sr.a_quiescing_command_is_running(path, ()) is False

    def test_missing_transcript_resolves_false(self):
        assert sr.a_quiescing_command_is_running(None, ("wrap-up",)) is False

    def test_unreadable_transcript_resolves_false(self):
        assert sr.a_quiescing_command_is_running("does-not-exist.jsonl", ("wrap-up",)) is False


class TestRepositoryRootDelegatesToSharedPlumbing:
    """`session_record.repository_root` is a thin, never-raising alias of
    `interlock.plumbing.repository_root` -- see that module's own docstring on why the two
    hosts share one implementation of this rather than each keeping its own copy."""

    def test_agrees_with_the_shared_plumbing_function(self, sandbox):
        from interlock.plumbing import repository_root as shared_repository_root
        assert sr.repository_root(str(sandbox)) == shared_repository_root(sandbox)

    def test_returns_none_outside_a_repository(self, tmp_path):
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        assert sr.repository_root(str(outside)) is None
