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
    # A later step whose predecessor is not done can never be marked done here,
    # but the ordering rule specifically prevents "in progress" from leaking
    # past a pending predecessor.
    statuses = bs.compute_statuses(REPO_ROOT, run_tests=False)
    # Every step number 0..10 is present.
    assert set(statuses) == {s.number for s in bs.STEPS}
    # No step is "in progress" unless its predecessor is done.
    done_or_progress = {bs.DONE, bs.IN_PROGRESS}
    for step in bs.STEPS[1:]:
        if statuses[step.number] in done_or_progress:
            assert statuses[step.number - 1] == bs.DONE


def test_actual_sequence_file_has_markers():
    text = (REPO_ROOT / "BUILDSEQUENCE.md").read_text(encoding="utf-8")
    assert bs.BEGIN_MARKER in text
    assert bs.END_MARKER in text
    # render() round-trips the real file without corrupting it.
    rendered = bs.render(text, bs.compute_statuses(REPO_ROOT, run_tests=False))
    assert bs.BEGIN_MARKER in rendered
    assert bs.END_MARKER in rendered
