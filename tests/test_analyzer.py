"""Tests for the analyzer's statistics on hand-computed fixtures.

Every formula the pilot reports is pinned here against values computed by hand,
so a regression in the math can never silently change a published number. An
integration test then runs the full analyze() against the committed pilot
evidence and checks internal consistency (not specific values — those belong
to the data, not the code).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deskbench.analyzer import (
    AnalyzerError,
    analyze,
    mae,
    mean,
    mess_penalty,
    pearson,
    sample_std,
    silent_failure_stats,
)

REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Pure math on hand-computed fixtures
# --------------------------------------------------------------------------- #
def test_mean_and_std():
    assert mean([2, 4, 6]) == pytest.approx(4.0)
    # ddof=1: std of [2,4,6] = sqrt(((-2)^2+0+2^2)/2) = 2.0
    assert sample_std([2, 4, 6]) == pytest.approx(2.0)
    assert sample_std([3.0]) is None  # n<2: undefined, never fabricated


def test_pearson_hand_computed():
    # Perfectly correlated and anti-correlated.
    assert pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert pearson([1, 2, 3], [6, 4, 2]) == pytest.approx(-1.0)
    # Hand-computed: xs=[1,2,3,4], ys=[1,3,2,4] -> r = 0.8
    assert pearson([1, 2, 3, 4], [1, 3, 2, 4]) == pytest.approx(0.8)
    # Zero variance on one side: undefined, reported as None, never 0 or 1.
    assert pearson([3, 3, 3], [1, 2, 3]) is None
    with pytest.raises(AnalyzerError):
        pearson([1, 2], [1, 2, 3])


def test_mae_hand_computed():
    assert mae([1, 2, 3], [2, 2, 5]) == pytest.approx((1 + 0 + 2) / 3)
    with pytest.raises(AnalyzerError):
        mae([1], [])


def test_mess_penalty_formula_matches_methodology():
    # Two core criteria, weights 0.30 and 0.10 -> relative 0.75 / 0.25.
    core_weights = {"a": 0.30, "b": 0.10}
    clean = {"a": [5, 5], "b": [4, 4]}
    messy = {"a": [3, 3], "b": [4, 2]}
    # a: 5-3 = 2 ; b: 4-3 = 1 ; penalty = 0.75*2 + 0.25*1 = 1.75
    assert mess_penalty(clean, messy, core_weights) == pytest.approx(1.75)


def test_mess_penalty_sign_convention():
    # Model does WORSE on messy -> positive penalty (mess degraded it).
    core = {"a": 1.0}
    assert mess_penalty({"a": [4]}, {"a": [2]}, core) == pytest.approx(2.0)
    # Model does better on messy -> negative.
    assert mess_penalty({"a": [2]}, {"a": [4]}, core) == pytest.approx(-2.0)


def test_mess_penalty_refuses_missing_core_scores():
    with pytest.raises(AnalyzerError):
        mess_penalty({"a": [5]}, {}, {"a": 1.0})


def test_silent_failure_counts_and_na_exclusion():
    # 2 silent, 1 flagged, 2 na -> rate = 2/3; na never enters the denominator.
    stats = silent_failure_stats([True, True, False, None, None])
    assert stats == {"silent": 2, "flagged": 1, "na_excluded": 2, "rate": pytest.approx(0.667)}
    # No wrong answers at all -> rate is None (undefined), not 0.
    assert silent_failure_stats([None, None])["rate"] is None


# --------------------------------------------------------------------------- #
# Integration against the committed pilot evidence (consistency, not values)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def summary():
    if not any((REPO / "results" / "scores").glob("*.json")):
        pytest.skip("pilot evidence not present")
    return analyze(
        REPO / "tasks",
        REPO / "results" / "raw",
        REPO / "results" / "scores",
        REPO / "results" / "human",
    )


def test_summary_counts_are_consistent(summary):
    m = summary["matrix"]
    assert m["n_judge_scores"] == m["n_human_grades"] == 48
    assert summary["agreement"]["n_paired"] == 48
    assert summary["agreement"]["n_unpaired"] == 0
    assert len(m["models"]) == 4
    assert len(m["twin_pairs"]) == 2


def test_summary_leaderboard_traceable(summary):
    # Every mean must equal the mean of its own listed per-run values.
    for row in summary["leaderboard"]:
        for source in ("judge", "human"):
            runs = [r["weighted_total"] for r in row[source]["per_run"]]
            assert row[source]["n_runs"] == len(runs) == 12
            assert row[source]["mean_overall"] == pytest.approx(mean(runs), abs=5e-4)


def test_summary_penalty_recomputable(summary):
    # per-model penalty is the mean of its per-pair penalties.
    for pm in summary["mess_penalty"]["per_model"]:
        pairs = [r for r in summary["mess_penalty"]["per_pair"] if r["model"] == pm["model"]]
        assert pm["judge"] == pytest.approx(mean([r["judge"] for r in pairs]), abs=1e-3)
        assert pm["human"] == pytest.approx(mean([r["human"] for r in pairs]), abs=1e-3)


def test_summary_silent_failure_totals(summary):
    for row in summary["silent_failure"]:
        assert row["silent"] + row["flagged"] + row["na_excluded"] == 12
