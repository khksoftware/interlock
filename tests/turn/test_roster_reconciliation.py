# SPDX-License-Identifier: Apache-2.0
"""Tests for `interlock/turn/roster_reconciliation.py`: pure helpers plus a real
end-to-end subprocess pair proving the block fires on the unregistered-live-dispatch
shape and clears once the roster is corrected."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from .conftest import (
    dispatch_entry, notification_entry, quiescing_entry, run_hook_subprocess,
    write_session_record, write_transcript,
)

HOOK_PATH = (
    Path(__file__).resolve().parent.parent.parent / "src" / "interlock" / "turn"
    / "roster_reconciliation.py"
)
_spec = importlib.util.spec_from_file_location("roster_reconciliation", HOOK_PATH)
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)


# --- pure helpers -------------------------------------------------------------------

class TestExtractIds:
    def test_uppercase_id_matches_default_pattern(self):
        assert hook.extract_ids("PROJ-101 turn-boundary check") == {"PROJ-101"}

    def test_lowercase_slug_matches_case_insensitively(self):
        assert hook.extract_ids("proj-101-core-review") == {"PROJ-101"}

    def test_multiple_ids_in_one_description(self):
        assert hook.extract_ids("PROJ-101 blocks on OPS-9") == {"PROJ-101", "OPS-9"}

    def test_no_id_returns_empty(self):
        assert hook.extract_ids("core review remainder") == frozenset()

    def test_empty_text_returns_empty(self):
        assert hook.extract_ids("") == frozenset()
        assert hook.extract_ids(None) == frozenset()


class TestExtractObservedRoster:
    def test_dispatch_with_no_notification_is_outstanding(self, tmp_path):
        path = write_transcript(tmp_path, [dispatch_entry("a1", "PROJ-999 unregistered work")])
        roster = hook.extract_observed_roster(str(path))
        assert roster["readable"] is True
        assert roster["outstanding"] == {"a1": "PROJ-999 unregistered work"}

    def test_dispatch_followed_by_notification_is_not_outstanding(self, tmp_path):
        path = write_transcript(tmp_path, [
            dispatch_entry("a1", "PROJ-999 unregistered work"),
            notification_entry("a1"),
        ])
        roster = hook.extract_observed_roster(str(path))
        assert roster["outstanding"] == {}
        assert "a1" in roster["notified"]

    def test_sidechain_dispatch_is_excluded(self, tmp_path):
        path = write_transcript(tmp_path, [dispatch_entry("a1", "PROJ-999 nested", sidechain=True)])
        roster = hook.extract_observed_roster(str(path))
        assert roster["dispatched"] == {}

    def test_missing_transcript_path_is_not_readable(self):
        assert hook.extract_observed_roster(None)["readable"] is False

    def test_malformed_json_lines_are_skipped_not_fatal(self, tmp_path):
        path = tmp_path / "t.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            handle.write("not json at all\n")
            handle.write(json.dumps(dispatch_entry("a1", "PROJ-999 real one")) + "\n")
        roster = hook.extract_observed_roster(str(path))
        assert roster["readable"] is True
        assert "a1" in roster["outstanding"]


class TestCompare:
    def test_matched_pair_produces_no_findings(self):
        a, b_resolved, b_unresolved = hook.compare(("PROJ-101",), {"a1": "PROJ-101 turn-boundary check"})
        assert (a, b_resolved, b_unresolved) == ((), (), ())

    def test_register_row_with_no_observed_dispatch_is_direction_a(self):
        a, b_resolved, _ = hook.compare(("PROJ-101",), {})
        assert a == ("PROJ-101",)
        assert b_resolved == ()

    def test_observed_dispatch_with_no_register_row_is_direction_b_resolved(self):
        a, b_resolved, b_unresolved = hook.compare((), {"a1": "PROJ-999 unregistered"})
        assert a == ()
        assert b_resolved == (("a1", ("PROJ-999",)),)
        assert b_unresolved == ()

    def test_unresolvable_description_is_its_own_bucket(self):
        _, b_resolved, b_unresolved = hook.compare((), {"a1": "no id here at all"})
        assert b_resolved == ()
        assert b_unresolved == ("a1",)


class TestBuildMessages:
    def test_refuse_reason_names_the_agent_and_ids(self):
        reason = hook.build_refuse_reason((("a1", ("PROJ-999",)),), (), ())
        assert "a1" in reason
        assert "PROJ-999" in reason

    def test_warn_message_names_direction_a_rows(self):
        message = hook.build_warn_message(("PROJ-101",), ())
        assert "PROJ-101" in message
        assert "not necessarily wrong".upper() in message.upper()


# --- end-to-end (real subprocess) ---------------------------------------------------

def test_unregistered_live_dispatch_blocks(sandbox):
    """RED: a dispatch outstanding in this session's own transcript, with no matching
    roster entry at all."""
    write_session_record(sandbox, roster={"state": "enumerated", "entries": []}, queue=[])
    transcript = write_transcript(sandbox, [dispatch_entry("a1", "PROJ-999 unregistered work")])
    proc = run_hook_subprocess("roster_reconciliation.py", sandbox, {
        "transcript_path": str(transcript), "stop_hook_active": False,
    })
    assert proc.returncode == 0, proc.stderr
    decision = json.loads(proc.stdout)
    assert decision["decision"] == "block"
    assert "PROJ-999" in decision["reason"]


def test_registering_the_row_clears_the_block(sandbox):
    """GREEN counterpart: same transcript, roster now carries the matching entry."""
    write_session_record(sandbox, roster={"state": "enumerated", "entries": [{"id": "PROJ-999"}]}, queue=[])
    transcript = write_transcript(sandbox, [dispatch_entry("a1", "PROJ-999 unregistered work")])
    proc = run_hook_subprocess("roster_reconciliation.py", sandbox, {
        "transcript_path": str(transcript), "stop_hook_active": False,
    })
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_register_row_with_no_observed_dispatch_warns_not_blocks(sandbox):
    write_session_record(sandbox, roster={"state": "enumerated", "entries": [{"id": "PROJ-101"}]}, queue=[])
    transcript = write_transcript(sandbox, [])
    proc = run_hook_subprocess("roster_reconciliation.py", sandbox, {
        "transcript_path": str(transcript), "stop_hook_active": False,
    })
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert "decision" not in payload
    assert "PROJ-101" in payload["systemMessage"]


def test_not_observable_state_suppresses_everything(sandbox):
    write_session_record(sandbox, roster={"state": "not-observable", "entries": []}, queue=[])
    transcript = write_transcript(sandbox, [dispatch_entry("a1", "PROJ-999 unregistered work")])
    proc = run_hook_subprocess("roster_reconciliation.py", sandbox, {
        "transcript_path": str(transcript), "stop_hook_active": False,
    })
    assert proc.stdout.strip() == ""


def test_quiescing_command_suppresses_the_whole_check(sandbox):
    write_session_record(sandbox, roster={"state": "enumerated", "entries": []}, queue=[])
    transcript = write_transcript(sandbox, [
        dispatch_entry("a1", "PROJ-999 unregistered work"),
        quiescing_entry("wrap-up"),
    ])
    proc = run_hook_subprocess("roster_reconciliation.py", sandbox, {
        "transcript_path": str(transcript), "stop_hook_active": False,
    })
    assert proc.stdout.strip() == ""


def test_stop_hook_active_short_circuits(sandbox):
    write_session_record(sandbox, roster={"state": "enumerated", "entries": []}, queue=[])
    transcript = write_transcript(sandbox, [dispatch_entry("a1", "PROJ-999 unregistered work")])
    proc = run_hook_subprocess("roster_reconciliation.py", sandbox, {
        "transcript_path": str(transcript), "stop_hook_active": True,
    })
    assert proc.stdout.strip() == ""


def test_repo_with_no_session_record_is_a_scope_miss(sandbox):
    transcript = write_transcript(sandbox, [dispatch_entry("a1", "PROJ-999 unregistered work")])
    proc = run_hook_subprocess("roster_reconciliation.py", sandbox, {
        "transcript_path": str(transcript), "stop_hook_active": False,
    })
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_custom_id_pattern_is_honoured(sandbox):
    write_session_record(sandbox, roster={"state": "enumerated", "entries": []}, queue=[])
    transcript = write_transcript(sandbox, [dispatch_entry("a1", "TICKET#4471 unregistered work")])
    proc = run_hook_subprocess("roster_reconciliation.py", sandbox, {
        "transcript_path": str(transcript), "stop_hook_active": False,
    }, env={"INTERLOCK_ID_PATTERN": r"TICKET#\d+"})
    decision = json.loads(proc.stdout)
    assert decision["decision"] == "block"
    assert "TICKET#4471" in decision["reason"]


def test_c2_d03_reconciliation_uses_configured_unique_platform(sandbox):
    document = {"platforms": [
        {"platform": "other", "roster": {"state": "enumerated", "entries": []}, "queue": []},
        {"platform": "default", "roster": {"state": "enumerated", "entries": []}, "queue": []},
    ]}
    path = sandbox / ".interlock" / "session_record.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    transcript = write_transcript(sandbox, [dispatch_entry("a1", "PROJ-999 unregistered work")])
    proc = run_hook_subprocess("roster_reconciliation.py", sandbox, {
        "transcript_path": str(transcript), "stop_hook_active": False,
    })
    assert json.loads(proc.stdout)["decision"] == "block"


def test_c2_d04_unselected_roster_entry_cannot_satisfy_reconciliation(sandbox):
    document = {"platforms": [
        {
            "platform": "other",
            "roster": {"state": "enumerated", "entries": [{"id": "PROJ-999"}]},
            "queue": [],
        },
        {"platform": "default", "roster": {"state": "enumerated", "entries": []}, "queue": []},
    ]}
    path = sandbox / ".interlock" / "session_record.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    transcript = write_transcript(sandbox, [dispatch_entry("a1", "PROJ-999 unregistered work")])
    proc = run_hook_subprocess("roster_reconciliation.py", sandbox, {
        "transcript_path": str(transcript), "stop_hook_active": False,
    })
    assert json.loads(proc.stdout)["decision"] == "block"


def test_unarmed_worktree_never_blocks_even_on_the_red_shape(sandbox):
    write_session_record(sandbox, roster={"state": "enumerated", "entries": []}, queue=[])
    transcript = write_transcript(sandbox, [dispatch_entry("a1", "PROJ-999 unregistered work")])
    proc = run_hook_subprocess("roster_reconciliation.py", sandbox, {
        "transcript_path": str(transcript), "stop_hook_active": False,
    }, armed=False)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""
