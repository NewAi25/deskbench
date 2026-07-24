"""Tests for the build-status certifier.

BUILDSEQUENCE.md rule 3: "the tool that certifies the work must itself be
certified." These tests exercise the pure logic (rendering + status ordering)
without spawning nested pytest runs (``run_tests=False``).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_status as bs  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

SAMPLE_TABLE = """\
intro text
<!-- STATUS:BEGIN -->

| Step | What | Module(s) | Definition of Done | Status |
|------|------|-----------|--------------------|--------|
| 0 | Repo & scaffolding | — | files exist | ⬜ pending |
| 1 | Schemas | schemas.py | tests pass | ⬜ pending |

<!-- STATUS:END -->
legend
"""


def test_render_sets_status_glyph():
    out = bs.render(SAMPLE_TABLE, {0: bs.DONE, 1: bs.IN_PROGRESS})
    assert "| 0 | Repo & scaffolding | — | files exist | ✅ done |" in out
    assert "| 1 | Schemas | schemas.py | tests pass | 🟨 in progress |" in out


def test_render_is_idempotent():
    once = bs.render(SAMPLE_TABLE, {0: bs.DONE, 1: bs.PENDING})
    twice = bs.render(once, {0: bs.DONE, 1: bs.PENDING})
    assert once == twice


def test_render_only_touches_rows_between_markers():
    poisoned = SAMPLE_TABLE.replace("legend", "| 0 | outside | x | y | ⬜ pending |")
    out = bs.render(poisoned, {0: bs.DONE})
    # The row after STATUS:END must be left untouched.
    assert "| 0 | outside | x | y | ⬜ pending |" in out


def test_render_preserves_trailing_newline():
    assert bs.render(SAMPLE_TABLE, {0: bs.DONE}).endswith("\n")
    assert not bs.render(SAMPLE_TABLE.rstrip("\n"), {0: bs.DONE}).endswith("\n")


def test_step_zero_is_done_on_real_repo():
    # File-existence checks only (no nested pytest); Step 0's artifacts exist.
    statuses = bs.compute_statuses(REPO_ROOT, run_tests=False)
    assert statuses[0] == bs.DONE


def test_ordering_blocks_out_of_sequence_completion():
    # The ordering rule prevents "in progress" from leaking past a pending
    # predecessor. A DONE step may follow a regressed (🟨) one: tightening an
    # earlier step's DoD must not unwind later verified work (BUILDSEQUENCE
    # rule 1, honest-regression note).
    statuses = bs.compute_statuses(REPO_ROOT, run_tests=False)
    # Every step number 0..10 is present.
    assert set(statuses) == {s.number for s in bs.STEPS}
    # No step is "in progress" unless its predecessor is done.
    for step in bs.STEPS[1:]:
        if statuses[step.number] == bs.IN_PROGRESS:
            assert statuses[step.number - 1] == bs.DONE


def test_saturation_predicate_requires_recorded_result(tmp_path):
    # Audit F3: the predicate must demand a RECORDED result, not a promise.
    log = tmp_path / "BUILD_LOG.md"
    log.write_text("Saturation check — status: PENDING maintainer run.\n", encoding="utf-8")
    assert bs.saturation_recorded(tmp_path) is False  # a promise is not a result
    log.write_text(
        "## Probe\nSATURATION RESULT: T01 spread 2-4, T02 spread 1-4; not saturated.\n",
        encoding="utf-8",
    )
    assert bs.saturation_recorded(tmp_path) is True
    # The marker must start a line — an inline mention doesn't count.
    log.write_text("we discussed the SATURATION RESULT: convention here\n", encoding="utf-8")
    assert bs.saturation_recorded(tmp_path) is False


def test_saturation_predicate_accepts_recorded_formats(tmp_path):
    # The two formats actually used in BUILD_LOG: bolded, and bolded with a
    # parenthetical before the colon. Both are genuine recorded results and
    # must count — rejecting them over Markdown would invert F3's fix.
    log = tmp_path / "BUILD_LOG.md"
    log.write_text(
        "**SATURATION RESULT: T01 gemini-flash 2.50/5, llama-3.3-70b 2.50/5.**\n",
        encoding="utf-8",
    )
    assert bs.saturation_recorded(tmp_path) is True
    log.write_text(
        "**SATURATION RESULT (hardened T02): T02 2.40/5 — ceiling broken.**\n",
        encoding="utf-8",
    )
    assert bs.saturation_recorded(tmp_path) is True


def test_step3_tracks_saturation_recording():
    # Step 3 is done only when a saturation result is recorded; with the real
    # repo's recorded probes this must now read done.
    statuses = bs.compute_statuses(REPO_ROOT, run_tests=False)
    if bs.saturation_recorded(REPO_ROOT):
        assert statuses[3] == bs.DONE
    else:
        assert statuses[3] == bs.IN_PROGRESS


def test_twin_suite_predicate_on_real_repo():
    # MVP step 6 DoD: the authored twin pairs must satisfy the predicate on the
    # real repo (2 clean tasks, each twin_of a valid messy dir).
    assert bs.twin_suite_validates(REPO_ROOT) is True


def test_pilot_run_predicate_false_before_any_run():
    # No results exist yet; the step-7 predicate must not report done.
    tmp_empty = REPO_ROOT  # results/raw and results/scores are empty pre-run
    raw = list((tmp_empty / "results" / "raw").glob("*.json"))
    if not raw:  # guard: only meaningful before the pilot run has happened
        assert bs.pilot_run_complete(tmp_empty) is False


def test_actual_sequence_file_has_markers():
    text = (REPO_ROOT / "BUILDSEQUENCE.md").read_text(encoding="utf-8")
    assert bs.BEGIN_MARKER in text
    assert bs.END_MARKER in text
    # render() round-trips the real file without corrupting it.
    rendered = bs.render(text, bs.compute_statuses(REPO_ROOT, run_tests=False))
    assert bs.BEGIN_MARKER in rendered
    assert bs.END_MARKER in rendered
