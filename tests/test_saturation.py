"""Tests for the saturation probe's pure helpers (no network).

The live run needs API keys and is never exercised in CI; these tests certify
the prompt assembly, judge-JSON parsing, weighting, and the saturation verdict.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import saturation_check as sc  # noqa: E402

from deskbench import schemas  # noqa: E402

T01 = REPO_ROOT / "tasks" / "T01-inbox-triage"


def test_build_prompt_inlines_artifacts():
    task = schemas.load_task(T01 / "task.yaml")
    prompt = sc.build_prompt(task, T01)
    assert "MATERIALS" in prompt
    # Every declared artifact's content is present.
    for name in task.artifacts:
        assert name in prompt
    assert "Board deck" in prompt  # a phrase from inbox.md


def test_parse_judge_scores_ok():
    rubric = schemas.load_rubric(T01 / "rubric.yaml")
    names = [c.name for c in rubric.criteria]
    reply = 'Here you go: {"scores": {' + ", ".join(f'"{n}": 3' for n in names) + "}}"
    scores = sc.parse_judge_scores(reply, rubric)
    assert set(scores) == set(names)
    assert all(v == 3 for v in scores.values())


def test_parse_judge_scores_rejects_incomplete():
    rubric = schemas.load_rubric(T01 / "rubric.yaml")
    first = rubric.criteria[0].name
    reply = f'{{"scores": {{"{first}": 5}}}}'
    with pytest.raises(ValueError):
        sc.parse_judge_scores(reply, rubric)


def test_parse_judge_scores_needs_json():
    rubric = schemas.load_rubric(T01 / "rubric.yaml")
    with pytest.raises(ValueError):
        sc.parse_judge_scores("no json here", rubric)


def test_weighted_total_matches_hand_calc():
    rubric = schemas.load_rubric(T01 / "rubric.yaml")
    perfect = {c.name: 5 for c in rubric.criteria}
    assert sc.weighted_total(perfect, rubric) == pytest.approx(5.0)
    lowest = {c.name: 1 for c in rubric.criteria}
    assert sc.weighted_total(lowest, rubric) == pytest.approx(1.0)


def test_weighted_total_respects_weights():
    rubric = schemas.load_rubric(T01 / "rubric.yaml")
    # Top criterion 5, rest 1: total should exceed a flat 1 but stay below 5.
    scores = {c.name: 1 for c in rubric.criteria}
    scores[rubric.criteria[0].name] = 5
    total = sc.weighted_total(scores, rubric)
    assert 1.0 < total < 5.0


def test_is_saturated():
    assert sc.is_saturated([4.0, 4.5, 5.0]) is True
    assert sc.is_saturated([4.0, 3.9, 4.8]) is False
    assert sc.is_saturated([]) is False
