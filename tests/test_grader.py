"""Tests for the grader (Box 4). The judge is mocked — no keys, no network.

Covers: valid grading + weighting; auto-fail forcing 0; reject-and-retry on a
malformed judge reply; hard failure after the attempt budget; the JSON contract
(missing/unknown/duplicate criteria, bad score, empty rationale); that grading
uses the held-out judge (never a leaderboard model); and the committed fixture.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from deskbench.grader import (
    GraderError,
    JudgeParseError,
    build_judge_prompt,
    grade,
    grade_raw_result,
    parse_judge_response,
    weighted_total,
)
from deskbench.registry import Registry, load_registry
from deskbench.schemas import RawResult, Score, load_rubric, load_task

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "config" / "models.yaml"
T01 = REPO_ROOT / "tasks" / "T01-inbox-triage"
FIXTURES = REPO_ROOT / "tests" / "fixtures"

RUBRIC = load_rubric(T01 / "rubric.yaml")
TASK = load_task(T01 / "task.yaml")
REFERENCE = (T01 / "reference.md").read_text(encoding="utf-8")


def _registry(tmp_path) -> Registry:
    return load_registry(CONFIG, cache_dir=tmp_path / "cache", retry_wait_min=0, retry_wait_max=0)


def _judge_reply(score=3, triggered=False) -> str:
    crits = [
        {"name": c.name, "score": score, "rationale": f"Matches the score-{score} anchor."}
        for c in RUBRIC.criteria
    ]
    return json.dumps({"criteria": crits, "auto_fail": {"triggered": triggered, "reason": ""}})


def _mock_judge(monkeypatch, reply_fn):
    """Patch the provider call; records the model configs it was invoked with."""
    seen: list[str] = []

    def fake(self, cfg, prompt, sampling):
        seen.append(cfg.id)
        return (reply_fn(), 100, 40)

    monkeypatch.setattr(Registry, "_raw_completion", fake)
    return seen


def _grade(reg, output="some answer", **kw):
    return grade(
        reg,
        task=TASK,
        rubric=RUBRIC,
        reference=REFERENCE,
        output=output,
        task_hash="sha256:deadbeef0001",
        model_id="gemini-flash",
        run_index=0,
        **kw,
    )


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_grade_produces_valid_score(tmp_path, monkeypatch):
    _mock_judge(monkeypatch, lambda: _judge_reply(score=3))
    reg = _registry(tmp_path)
    score = _grade(reg)
    assert isinstance(score, Score)
    assert score.weighted_total == pytest.approx(3.0)
    assert {cs.name for cs in score.criterion_scores} == {c.name for c in RUBRIC.criteria}
    assert score.judge_model == reg.judge_id
    assert score.rubric_hash.startswith("sha256:")
    assert score.failure_modes == []  # human-assigned later (fix #5)


def test_weighted_total_extremes():
    perfect = [
        parse_judge_response(_judge_reply(score=5), RUBRIC)[0][i]
        for i in range(len(RUBRIC.criteria))
    ]
    assert weighted_total(perfect, RUBRIC) == pytest.approx(5.0)
    worst, _, _ = parse_judge_response(_judge_reply(score=1), RUBRIC)
    assert weighted_total(worst, RUBRIC) == pytest.approx(1.0)


def test_weighted_total_normalizes_clean_rubric():
    # A clean rubric's core-only weights sum to < 1.0; the total must still be
    # on the 1-5 scale so twin totals are comparable (MVP mess-penalty design).
    from deskbench.schemas import CriterionScore, Rubric

    clean = Rubric.model_validate(
        {
            "task_id": "Tc",
            "variant": "clean",
            "criteria": [
                {
                    "name": "a",
                    "weight": 0.30,
                    "description": "d",
                    "anchors": {1: "x", 3: "y", 5: "z"},
                },
                {
                    "name": "b",
                    "weight": 0.10,
                    "description": "d",
                    "anchors": {1: "x", 3: "y", 5: "z"},
                },
            ],
        }
    )
    scores = [
        CriterionScore(name="a", score=5, judge_rationale="anchor 5"),
        CriterionScore(name="b", score=1, judge_rationale="anchor 1"),
    ]
    # (5*0.30 + 1*0.10) / 0.40 = 4.0 — NOT 1.6, which the unnormalized sum gives.
    assert weighted_total(scores, clean) == pytest.approx(4.0)
    perfect = [CriterionScore(name=n, score=5, judge_rationale="r") for n in ("a", "b")]
    assert weighted_total(perfect, clean) == pytest.approx(5.0)


def test_grade_uses_held_out_judge(tmp_path, monkeypatch):
    seen = _mock_judge(monkeypatch, lambda: _judge_reply(score=4))
    reg = _registry(tmp_path)
    _grade(reg)
    # Only the judge model was ever called, and it isn't a leaderboard model.
    assert set(seen) == {reg.judge_id}
    assert reg.judge_id not in reg.leaderboard_ids


# --------------------------------------------------------------------------- #
# Auto-fail
# --------------------------------------------------------------------------- #
def test_auto_fail_forces_zero(tmp_path, monkeypatch):
    _mock_judge(monkeypatch, lambda: _judge_reply(score=5, triggered=True))
    reg = _registry(tmp_path)
    score = _grade(reg)
    assert score.auto_fail_triggered is True
    assert score.weighted_total == 0.0  # forced to 0 despite 5s


# --------------------------------------------------------------------------- #
# Reject-and-retry
# --------------------------------------------------------------------------- #
def test_reject_and_retry_recovers(tmp_path, monkeypatch):
    replies = iter(["not json at all", "still {broken", _judge_reply(score=3)])
    reg = _registry(tmp_path)
    _mock_judge(monkeypatch, lambda: next(replies))
    score = _grade(reg, max_attempts=3)  # third attempt is valid
    assert score.weighted_total == pytest.approx(3.0)


def test_persistent_bad_json_raises(tmp_path, monkeypatch):
    _mock_judge(monkeypatch, lambda: "never valid json")
    reg = _registry(tmp_path)
    with pytest.raises(GraderError) as exc:
        _grade(reg, max_attempts=3)
    assert "failed to parse" in str(exc.value)


# --------------------------------------------------------------------------- #
# JSON contract
# --------------------------------------------------------------------------- #
def test_parse_rejects_missing_criterion():
    entries = [{"name": c.name, "score": 3, "rationale": "ok"} for c in RUBRIC.criteria[:-1]]
    reply = json.dumps({"criteria": entries})
    with pytest.raises(JudgeParseError) as exc:
        parse_judge_response(reply, RUBRIC)
    assert "omitted" in str(exc.value)


def test_parse_rejects_unknown_criterion():
    reply = json.dumps({"criteria": [{"name": "made-up", "score": 3, "rationale": "x"}]})
    with pytest.raises(JudgeParseError):
        parse_judge_response(reply, RUBRIC)


def test_parse_rejects_out_of_range_score():
    entries = [{"name": c.name, "score": 9, "rationale": "x"} for c in RUBRIC.criteria]
    with pytest.raises(JudgeParseError):
        parse_judge_response(json.dumps({"criteria": entries}), RUBRIC)


def test_parse_rejects_empty_rationale():
    entries = [{"name": c.name, "score": 3, "rationale": ""} for c in RUBRIC.criteria]
    with pytest.raises(JudgeParseError):
        parse_judge_response(json.dumps({"criteria": entries}), RUBRIC)


def test_parse_rejects_duplicate_criterion():
    first = RUBRIC.criteria[0].name
    entries = [{"name": first, "score": 3, "rationale": "x"} for _ in range(2)]
    with pytest.raises(JudgeParseError):
        parse_judge_response(json.dumps({"criteria": entries}), RUBRIC)


def test_parse_rejects_non_json():
    with pytest.raises(JudgeParseError):
        parse_judge_response("the model refused to answer", RUBRIC)


def test_parse_tolerates_prose_around_json():
    reply = "Sure! " + _judge_reply(score=4) + "\nHope that helps."
    scores, triggered, _ = parse_judge_response(reply, RUBRIC)
    assert len(scores) == len(RUBRIC.criteria)
    assert triggered is False


# --------------------------------------------------------------------------- #
# End-to-end via RawResult, and the judge prompt content
# --------------------------------------------------------------------------- #
def test_grade_raw_result_end_to_end(tmp_path, monkeypatch):
    _mock_judge(monkeypatch, lambda: _judge_reply(score=4))
    reg = _registry(tmp_path)
    raw = RawResult(
        task_id="T01-inbox-triage",
        model_id="llama-3.3-70b",
        run_index=1,
        output="A plausible triage answer.",
        timestamp=datetime(2026, 7, 11, tzinfo=UTC),
        task_hash="sha256:abc123abc123",
    )
    score = grade_raw_result(reg, raw, T01)
    assert score.task_id == "T01-inbox-triage"
    assert score.model_id == "llama-3.3-70b"
    assert score.run_index == 1
    assert score.weighted_total == pytest.approx(4.0)


def test_judge_prompt_instructs_anchor_grading():
    prompt = build_judge_prompt(TASK, RUBRIC, REFERENCE, "candidate output")
    low = prompt.lower()
    assert "not similarity to the reference" in low or "not the grading target" in low
    # Anchors and auto-fail conditions are present.
    assert "score 5:" in prompt
    assert "AUTO-FAIL" in prompt
    for c in RUBRIC.criteria:
        assert c.name in prompt


def test_score_fixture_validates():
    fixture = FIXTURES / "sample_score.json"
    score = Score.model_validate_json(fixture.read_text(encoding="utf-8"))
    assert score.task_id == "T01-inbox-triage"
    assert 0.0 <= score.weighted_total <= 5.0
    assert score.judge_model
