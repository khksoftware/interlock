# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

from interlock.git.absolute_local_path import (
    SPEC, staged_absolute_local_path_failures, staged_absolute_local_path_failures_from_config,
)
from interlock.git.hookkit import install, is_armed
from tests.conftest import run_git


class TestThePredicate:
    def test_a_windows_drive_letter_path_is_caught(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text(
            "See C:" + r"\Users\jdoe\repo\file.py for details" + "\n", encoding="utf-8",
        )
        run_git(sandbox, "add", "notes.md")
        failures = staged_absolute_local_path_failures(sandbox)
        assert len(failures) == 1
        assert "notes.md:1" in failures[0]

    def test_a_posix_home_directory_path_is_caught(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text(
            "See /" + "home/jdoe/project/file.py\n", encoding="utf-8",
        )
        run_git(sandbox, "add", "notes.md")
        assert len(staged_absolute_local_path_failures(sandbox)) == 1

    def test_a_macos_users_path_is_caught(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text(
            "See /" + "Users/jdoe/project/file.py\n", encoding="utf-8",
        )
        run_git(sandbox, "add", "notes.md")
        assert len(staged_absolute_local_path_failures(sandbox)) == 1

    def test_a_unc_path_is_caught(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text(
            "See " + "\\" + r"\server\share\folder\file.py" + "\n", encoding="utf-8",
        )
        run_git(sandbox, "add", "notes.md")
        assert len(staged_absolute_local_path_failures(sandbox)) == 1

    def test_a_relative_path_is_not_flagged(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text("See engineering/tests/thing.py\n", encoding="utf-8")
        run_git(sandbox, "add", "notes.md")
        assert staged_absolute_local_path_failures(sandbox) == ()

    def test_two_patterns_on_one_line_collapse_to_one_finding(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text(
            "C:" + r"\one\path and " + "/" + "home/two/path on one line\n", encoding="utf-8",
        )
        run_git(sandbox, "add", "notes.md")
        assert len(staged_absolute_local_path_failures(sandbox)) == 1

    def test_a_citation_exempts_one_named_line(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text(
            "Historical: C:" + r"\old\path was the old layout" + "\n", encoding="utf-8",
        )
        run_git(sandbox, "add", "notes.md")
        failures = staged_absolute_local_path_failures(
            sandbox, citations=({"path": "notes.md", "line_contains": "Historical"},),
        )
        assert failures == ()

    def test_deferred_scope_exempts_a_whole_prefix(self, sandbox: Path) -> None:
        (sandbox / "fixtures").mkdir()
        (sandbox / "fixtures" / "sample.txt").write_text(
            "C:" + r"\fake\example\path" + "\n", encoding="utf-8",
        )
        run_git(sandbox, "add", "fixtures/sample.txt")
        failures = staged_absolute_local_path_failures(
            sandbox, deferred_scope=({"path_prefix": "fixtures/"},),
        )
        assert failures == ()

    def test_a_deleted_path_is_not_scanned(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text(
            "C:" + r"\will\be\deleted" + "\n", encoding="utf-8",
        )
        run_git(sandbox, "add", "notes.md")
        run_git(sandbox, "commit", "-q", "-m", "add notes with a path")
        run_git(sandbox, "rm", "-q", "notes.md")
        assert staged_absolute_local_path_failures(sandbox) == ()


class TestTheJoinPassDoesNotRefuseOrdinaryProse:
    """Regression pins for false refusals an over-broad join predicate produced.

    The join fires on boundary characters, which is the only signal available where
    neither line matches alone. Firing on them unconditionally fused ordinary prose: a
    bare drive colon ending one line and a forward slash opening the next joins into
    something path-shaped that no author wrote. None of the cases here embeds a local
    path, and every one was refused before that shape was excluded.

    Pinned because the cost is asymmetric. A missed wrapped path is one undetected
    string; a gate that refuses good commits gets bypassed as a habit and then protects
    nothing at all.
    """

    def test_a_drive_letter_in_prose_above_a_posix_path_is_not_fused(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text(
            "drive D:" + "\n/dev/null is empty\n", encoding="utf-8",
        )
        run_git(sandbox, "add", "notes.md")
        assert staged_absolute_local_path_failures(sandbox) == ()

    def test_a_section_label_above_a_slash_line_is_not_fused(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text(
            "see section C:" + "\n/notes below\n", encoding="utf-8",
        )
        run_git(sandbox, "add", "notes.md")
        assert staged_absolute_local_path_failures(sandbox) == ()

    def test_a_ratio_above_a_fraction_is_not_fused(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text("the ratio was 3:\n/4 overall\n", encoding="utf-8")
        run_git(sandbox, "add", "notes.md")
        assert staged_absolute_local_path_failures(sandbox) == ()

class TestLineBreakEvasion:
    """`REVIEW_2026-08-21.md` Finding 1: per-line scanning alone is defeated by an
    ordinary line break -- a wrapped log paste, a hard-wrapped table cell. Re-measured
    directly, the real evading break positions are: Windows drive path, 2 of 32 (both
    inside the ``letter:separator`` sequence itself); POSIX ``/home/``, 10 of 30; POSIX
    ``/Users/``, 11 of 31; UNC, 8 of 25 -- roughly a third for the three longer-prefix
    forms. Position 1 (breaking right after the very first character) is one of the real
    evading positions for all four forms and is used below as the representative,
    previously-evading case each now has to be caught at."""

    def test_a_windows_drive_path_split_right_after_the_bare_letter_is_caught(
        self, sandbox: Path,
    ) -> None:
        full = "C:" + r"\Users\jdoe\Desktop\secret.txt"
        first, second = full[:1], full[1:]  # "C" / ":\Users\jdoe\Desktop\secret.txt"
        (sandbox / "notes.md").write_text(first + "\n" + second + "\n", encoding="utf-8")
        run_git(sandbox, "add", "notes.md")
        failures = staged_absolute_local_path_failures(sandbox)
        assert len(failures) == 1
        assert "notes.md:1" in failures[0]
        assert "line break" in failures[0]

    def test_a_posix_home_path_split_right_after_the_leading_separator_is_caught(
        self, sandbox: Path,
    ) -> None:
        full = "/" + "home/jdoe/projects/secret.txt"
        first, second = full[:1], full[1:]  # "/" / "home/jdoe/projects/secret.txt"
        (sandbox / "notes.md").write_text(first + "\n" + second + "\n", encoding="utf-8")
        run_git(sandbox, "add", "notes.md")
        failures = staged_absolute_local_path_failures(sandbox)
        assert len(failures) == 1
        assert "notes.md:1" in failures[0]
        assert "line break" in failures[0]

    def test_a_posix_users_path_split_right_after_the_leading_separator_is_caught(
        self, sandbox: Path,
    ) -> None:
        full = "/" + "Users/jdoe/projects/secret.txt"
        first, second = full[:1], full[1:]  # "/" / "Users/jdoe/projects/secret.txt"
        (sandbox / "notes.md").write_text(first + "\n" + second + "\n", encoding="utf-8")
        run_git(sandbox, "add", "notes.md")
        failures = staged_absolute_local_path_failures(sandbox)
        assert len(failures) == 1
        assert "notes.md:1" in failures[0]
        assert "line break" in failures[0]

    def test_a_unc_path_split_right_after_the_leading_separator_is_caught(
        self, sandbox: Path,
    ) -> None:
        full = "\\" + r"\server\share\secret.txt"
        first, second = full[:1], full[1:]  # "\" / "\server\share\secret.txt"
        (sandbox / "notes.md").write_text(first + "\n" + second + "\n", encoding="utf-8")
        run_git(sandbox, "add", "notes.md")
        failures = staged_absolute_local_path_failures(sandbox)
        assert len(failures) == 1
        assert "notes.md:1" in failures[0]
        assert "line break" in failures[0]

    def test_a_break_strictly_inside_a_path_segment_still_evades(self, sandbox: Path) -> None:
        """Documented residual, not a bug: a break touching neither a separator nor a
        colon on either side carries no signal that a path continues there, so the
        narrow join-aware pass deliberately does not attempt it (see the module
        docstring's "Line-break evasion" section)."""
        full = "/" + "home/jdoe/projects/secret.txt"
        first, second = full[:3], full[3:]  # "/ho" / "me/jdoe/projects/secret.txt"
        (sandbox / "notes.md").write_text(first + "\n" + second + "\n", encoding="utf-8")
        run_git(sandbox, "add", "notes.md")
        assert staged_absolute_local_path_failures(sandbox) == ()

    def test_a_line_already_reported_per_line_is_not_also_reported_by_the_join_pass(
        self, sandbox: Path,
    ) -> None:
        # Line 1 alone already embeds a complete path AND ends with a separator, so the
        # join-aware pass's own boundary heuristic would also fire on it -- it must not
        # produce a second finding for the same content.
        (sandbox / "notes.md").write_text(
            "See C:" + r"\Users\jdoe\Desktop\\" + "\n" + "more unrelated prose continues here.\n",
            encoding="utf-8",
        )
        run_git(sandbox, "add", "notes.md")
        failures = staged_absolute_local_path_failures(sandbox)
        assert len(failures) == 1
        assert "notes.md:1" in failures[0]
        assert "line break" not in failures[0]

    def test_a_citation_also_exempts_a_spanning_match(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text(
            "Historical citation: C" + "\n" + r":\old\path documented here" + "\n",
            encoding="utf-8",
        )
        run_git(sandbox, "add", "notes.md")
        failures = staged_absolute_local_path_failures(
            sandbox, citations=({"path": "notes.md", "line_contains": "Historical"},),
        )
        assert failures == ()

    def test_an_innocent_separator_boundary_with_no_second_separator_does_not_fire(
        self, sandbox: Path,
    ) -> None:
        # "/home/" ends line 1 (a real separator boundary, so the join is attempted), but
        # line 2 is ordinary prose with no second separator -- the pattern's own required
        # skeleton is never completed, so this must not be flagged just because the join
        # was attempted.
        (sandbox / "notes.md").write_text(
            "The shared directory lives at /" + "home/\ngrown teams collaborate there daily.\n",
            encoding="utf-8",
        )
        run_git(sandbox, "add", "notes.md")
        assert staged_absolute_local_path_failures(sandbox) == ()

    def test_an_innocent_drive_colon_boundary_does_not_fire(self, sandbox: Path) -> None:
        # Line 2 starts with ":" for an unrelated reason (ordinary punctuation, not a
        # drive letter's own colon) -- the join is attempted, but the colon is never
        # immediately followed by a separator, so the pattern never completes.
        (sandbox / "notes.md").write_text(
            "If that fails, use Plan B\n: contact support directly for manual intervention.\n",
            encoding="utf-8",
        )
        run_git(sandbox, "add", "notes.md")
        assert staged_absolute_local_path_failures(sandbox) == ()


class TestFromConfig:
    def test_reads_citations_and_deferred_scope_from_the_config_file(self, sandbox: Path) -> None:
        config = sandbox / "interlock.json"
        config.write_text(
            '{"absolute_local_path": {"deferred_scope": [{"path_prefix": "fixtures/"}]}}',
            encoding="utf-8",
        )
        run_git(sandbox, "add", "interlock.json")
        (sandbox / "fixtures").mkdir()
        (sandbox / "fixtures" / "sample.txt").write_text(
            "C:" + r"\fake\path" + "\n", encoding="utf-8",
        )
        run_git(sandbox, "add", "fixtures/sample.txt")
        assert staged_absolute_local_path_failures_from_config(sandbox) == ()

    def test_no_config_file_means_the_built_in_patterns_alone_apply(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text(
            "C:" + r"\no\config\here" + "\n", encoding="utf-8",
        )
        run_git(sandbox, "add", "notes.md")
        assert len(staged_absolute_local_path_failures_from_config(sandbox)) == 1


class TestTheBlockActuallyBlocks:
    def test_an_armed_worktree_refuses_a_real_commit_embedding_a_path(
        self, sandbox: Path, interpreter: Path,
    ) -> None:
        install(sandbox, SPEC, interpreter=interpreter)
        (sandbox / "leak.md").write_text(
            "C:" + r"\Users\jdoe\secret\notes" + "\n", encoding="utf-8",
        )
        run_git(sandbox, "add", "leak.md")
        result = run_git(sandbox, "commit", "-q", "-m", "oops")
        assert result.returncode != 0

    def test_an_unarmed_worktree_passes_the_identical_fixture(self, sandbox: Path, interpreter: Path) -> None:
        (sandbox / "leak.md").write_text(
            "C:" + r"\Users\jdoe\secret\notes" + "\n", encoding="utf-8",
        )
        run_git(sandbox, "add", "leak.md")
        result = run_git(sandbox, "commit", "-q", "-m", "unarmed, lands anyway")
        assert result.returncode == 0
        assert not is_armed(sandbox, SPEC)

    def test_an_ordinary_commit_passes_while_armed(self, sandbox: Path, interpreter: Path) -> None:
        install(sandbox, SPEC, interpreter=interpreter)
        (sandbox / "ordinary.txt").write_text("nothing to see here\n", encoding="utf-8")
        run_git(sandbox, "add", "ordinary.txt")
        result = run_git(sandbox, "commit", "-q", "-m", "ordinary")
        assert result.returncode == 0
