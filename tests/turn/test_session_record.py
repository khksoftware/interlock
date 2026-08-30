# SPDX-License-Identifier: Apache-2.0
"""Tests for `interlock.turn.session_record`, the shared reader both roster hooks depend
on."""
from __future__ import annotations

import json

from interlock.turn import config, session_record as sr


class TestPlatformNode:
    def test_multi_platform_document_finds_named_platform(self):
        document = {"platforms": [{"platform": "codex", "roster": {}}, {"platform": "claude", "roster": {"x": 1}}]}
        node = sr.platform_node(document, platform="claude")
        assert node == {"platform": "claude", "roster": {"x": 1}}

    def test_c2_p01_default_selector_chooses_default_not_index_zero(self):
        document = {"platforms": [
            {"platform": "other", "roster": {"wrong": True}},
            {"platform": "default", "roster": {"right": True}},
        ]}
        assert config.SESSION_PLATFORM == "default"
        assert sr.platform_node(document, platform=config.SESSION_PLATFORM)["roster"] == {"right": True}

    def test_missing_platform_name_returns_none(self):
        document = {"platforms": [{"platform": "codex"}]}
        assert sr.platform_node(document, platform="claude") is None

    def test_single_platform_document_falls_back_to_top_level(self):
        document = {"roster": {"state": "none", "entries": []}, "queue": []}
        assert sr.platform_node(document) is document

    def test_document_with_neither_shape_returns_none(self):
        assert sr.platform_node({"unrelated": True}) is None


class TestC2PlatformAndOpenRows:
    def test_c2_p02_absent_explicit_selector_returns_none(self):
        assert sr.platform_node({"platforms": [{"platform": "default"}]}, platform="other") is None

    def test_c2_p03_none_selector_returns_none(self):
        assert sr.platform_node({"platforms": [{"platform": "default"}]}, platform=None) is None

    def test_c2_p04_empty_selector_returns_none(self):
        assert sr.platform_node({"platforms": [{"platform": "default"}]}, platform="") is None

    def test_c2_p05_padded_selector_returns_none(self):
        assert sr.platform_node({"platforms": [{"platform": "default"}]}, platform=" default ") is None

    def test_c2_p06_non_string_selector_returns_none(self):
        assert sr.platform_node({"platforms": [{"platform": "default"}]}, platform=7) is None

    def test_c2_p07_duplicate_selected_platform_is_ambiguous(self):
        document = {"platforms": [{"platform": "default"}, {"platform": "default"}]}
        assert sr.platform_node(document, platform="default") is None

    def test_c2_p08_duplicate_unselected_platform_invalidates_population(self):
        document = {"platforms": [
            {"platform": "default"}, {"platform": "other"}, {"platform": "other"},
        ]}
        assert sr.platform_node(document, platform="default") is None

    def test_c2_p09_non_dict_platform_member_invalidates_population(self):
        document = {"platforms": [{"platform": "default"}, "other"]}
        assert sr.platform_node(document, platform="default") is None

    def test_c2_p10_missing_platform_identity_invalidates_population(self):
        document = {"platforms": [{"platform": "default"}, {}]}
        assert sr.platform_node(document, platform="default") is None

    def test_c2_p11_non_string_platform_identity_invalidates_population(self):
        document = {"platforms": [{"platform": "default"}, {"platform": 1}]}
        assert sr.platform_node(document, platform="default") is None

    def test_c2_p12_empty_platform_identity_invalidates_population(self):
        document = {"platforms": [{"platform": "default"}, {"platform": ""}]}
        assert sr.platform_node(document, platform="default") is None

    def test_c2_p13_non_list_platforms_returns_none(self):
        assert sr.platform_node({"platforms": {}}, platform="default") is None

    def test_c2_p14_top_level_shape_remains_unambiguous(self):
        document = {"roster": {}, "queue": []}
        assert sr.platform_node(document, platform=None) is document

    def test_c2_p15_queued_row_is_open(self):
        assert sr.open_row_ids({"queue": [{"id": "PROJ-1", "status": "queued"}]}) == frozenset({"PROJ-1"})

    def test_c2_p16_running_row_is_open(self):
        assert sr.open_row_ids({"queue": [{"id": "PROJ-1", "status": "running"}]}) == frozenset({"PROJ-1"})

    def test_c2_p17_blocked_row_is_open(self):
        assert sr.open_row_ids({"queue": [{"id": "PROJ-1", "status": "blocked"}]}) == frozenset({"PROJ-1"})

    def test_c2_p18_closed_row_is_terminal(self):
        assert sr.open_row_ids({"queue": [{"id": "PROJ-1", "status": "closed"}]}) == frozenset()

    def test_c2_p19_missing_status_is_not_open(self):
        assert sr.open_row_ids({"queue": [{"id": "PROJ-1"}]}) == frozenset()

    def test_c2_p20_null_status_is_not_open(self):
        assert sr.open_row_ids({"queue": [{"id": "PROJ-1", "status": None}]}) == frozenset()

    def test_c2_p21_non_string_status_is_not_open(self):
        assert sr.open_row_ids({"queue": [{"id": "PROJ-1", "status": 1}]}) == frozenset()

    def test_c2_p22_empty_status_is_not_open(self):
        assert sr.open_row_ids({"queue": [{"id": "PROJ-1", "status": ""}]}) == frozenset()

    def test_c2_p23_case_variant_status_is_not_open(self):
        assert sr.open_row_ids({"queue": [{"id": "PROJ-1", "status": "Queued"}]}) == frozenset()

    def test_c2_p24_unknown_status_is_not_open(self):
        assert sr.open_row_ids({"queue": [{"id": "PROJ-1", "status": "ready"}]}) == frozenset()

    def test_c2_p25_non_list_queue_is_immutable_empty(self):
        assert sr.open_row_ids({"queue": {}}) == frozenset()

    def test_c2_p26_non_dict_queue_row_is_ignored(self):
        assert sr.open_row_ids({"queue": [None, "row"]}) == frozenset()

    def test_c2_p27_missing_row_id_is_ignored(self):
        assert sr.open_row_ids({"queue": [{"status": "queued"}]}) == frozenset()

    def test_c2_p28_empty_row_id_is_ignored(self):
        assert sr.open_row_ids({"queue": [{"id": "", "status": "queued"}]}) == frozenset()

    def test_c2_p29_backticks_are_stripped(self):
        assert sr.open_row_ids({"queue": [{"id": "`PROJ-1`", "status": "queued"}]}) == frozenset({"PROJ-1"})

    def test_c2_p30_whitespace_is_stripped(self):
        assert sr.open_row_ids({"queue": [{"id": "  PROJ-1  ", "status": "queued"}]}) == frozenset({"PROJ-1"})

    def test_c2_p31_ids_are_case_normalized_once(self):
        node = {"queue": [
            {"id": "proj-1", "status": "queued"},
            {"id": "PROJ-1", "status": "running"},
        ]}
        assert sr.open_row_ids(node) == frozenset({"PROJ-1"})

    def test_c2_p32_result_is_immutable(self):
        result = sr.open_row_ids({"queue": [{"id": "PROJ-1", "status": "queued"}]})
        assert isinstance(result, frozenset)
        assert not hasattr(result, "add")

    def test_c3_p33_list_status_is_not_open(self):
        node = {"queue": [{"id": "PROJ-1", "status": ["queued"]}]}
        assert sr.open_row_ids(node) == frozenset()

    def test_c3_p34_dict_status_is_not_open(self):
        node = {"queue": [{"id": "PROJ-1", "status": {"value": "queued"}}]}
        assert sr.open_row_ids(node) == frozenset()

    def test_c3_p35_set_status_is_not_open(self):
        node = {"queue": [{"id": "PROJ-1", "status": {"queued"}}]}
        assert sr.open_row_ids(node) == frozenset()


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
