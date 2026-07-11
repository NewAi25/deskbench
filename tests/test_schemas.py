"""Tests for the four DeskBench data contracts and the versioning helpers.

Covers: loading valid task/rubric YAML; readable failures on malformed YAML
(the Step 1 DoD); weight-sum and anchor validation; content-hash determinism and
sensitivity (fix #2); sampling-params defaults on RawResult (fix #3); Score
bounds; and record-id slugification.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from deskbench import schemas
from deskbench.schemas import (
    Category,
    CriterionScore,
    RawResult,
    Rubric,
    SamplingParams,
    SchemaError,
    Score,
    Task,
    hash_rubric,
    hash_task_dir,
    load_rubric,
    load_task,
    record_id,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOOD_TASK_DIR = FIXTURES / "task_good"


# --------------------------------------------------------------------------- #
# Loading valid definitions
# --------------------------------------------------------------------------- #
def test_load_good_task():
    task = load_task(GOOD_TASK_DIR / "task.yaml")
    assert isinstance(task, Task)
    assert task.id == "T00-fixture-triage"
    assert task.category == "communication"
    assert task.difficulty == "medium"
    assert task.artifacts == ["emails.md"]
    assert task.content_hash is None  # authored files never carry a hash


def test_task_variant_defaults_to_messy_and_accepts_clean():
    task = load_task(GOOD_TASK_DIR / "task.yaml")
    assert task.variant == "messy"  # default when not declared
    clean = Task.model_validate(
        {
            "id": "T00c",
            "title": "clean twin",
            "category": "communication",
            "difficulty": "medium",
            "variant": "clean",
            "prompt": "do the work",
        }
    )
    assert clean.variant == "clean"
    with pytest.raises(ValidationError):
        Task.model_validate(
            {
                "id": "x",
                "title": "t",
                "category": "communication",
                "difficulty": "easy",
                "variant": "pristine",  # not a valid variant
                "prompt": "p",
            }
        )


def test_raw_result_carries_variant():
    r = RawResult(
        task_id="T00",
        model_id="m",
        run_index=0,
        variant="clean",
        output="x",
        timestamp=_now(),
        task_hash="sha256:abc123abc123",
    )
    assert r.variant == "clean"
    again = RawResult.model_validate_json(r.model_dump_json())
    assert again.variant == "clean"
    default = RawResult(
        task_id="T00",
        model_id="m",
        run_index=0,
        output="x",
        timestamp=_now(),
        task_hash="sha256:abc123abc123",
    )
    assert default.variant == "messy"


def test_load_good_rubric():
    rubric = load_rubric(GOOD_TASK_DIR / "rubric.yaml")
    assert isinstance(rubric, Rubric)
    assert rubric.task_id == "T00-fixture-triage"
    assert len(rubric.criteria) == 3
    assert abs(sum(c.weight for c in rubric.criteria) - 1.0) < 1e-9


def _criterion(name: str, weight: float, kind: str = "core") -> dict:
    return {
        "name": name,
        "weight": weight,
        "kind": kind,
        "description": "d",
        "anchors": {1: "a", 3: "b", 5: "c"},
    }


def test_criterion_kind_defaults_to_core_and_rejects_unknown():
    rubric = load_rubric(GOOD_TASK_DIR / "rubric.yaml")
    assert all(c.kind == "core" for c in rubric.criteria)  # default when not declared
    with pytest.raises(ValidationError):
        Rubric.model_validate({"task_id": "T", "criteria": [_criterion("c", 1.0, kind="noise")]})


def test_clean_rubric_core_only_weights_below_one():
    # A clean rubric keeps the messy twin's core weights verbatim, so < 1.0 is valid.
    clean = Rubric.model_validate(
        {
            "task_id": "Tc",
            "variant": "clean",
            "criteria": [_criterion("a", 0.30), _criterion("b", 0.15), _criterion("c", 0.10)],
        }
    )
    assert clean.variant == "clean"
    assert abs(sum(c.weight for c in clean.criteria) - 0.55) < 1e-9


def test_clean_rubric_rejects_mess_criteria():
    with pytest.raises(ValidationError) as exc:
        Rubric.model_validate(
            {
                "task_id": "Tc",
                "variant": "clean",
                "criteria": [_criterion("a", 0.30), _criterion("b", 0.25, kind="mess")],
            }
        )
    assert "only core criteria" in str(exc.value)


def test_clean_rubric_rejects_weights_over_one():
    with pytest.raises(ValidationError) as exc:
        Rubric.model_validate(
            {
                "task_id": "Tc",
                "variant": "clean",
                "criteria": [_criterion("a", 0.7), _criterion("b", 0.7)],
            }
        )
    assert "must not exceed 1.0" in str(exc.value)


def test_messy_rubric_still_requires_weights_sum_to_one():
    # The MVP twin change must not loosen the original messy-rubric invariant.
    with pytest.raises(ValidationError) as exc:
        Rubric.model_validate(
            {"task_id": "T", "criteria": [_criterion("a", 0.30), _criterion("b", 0.25, "mess")]}
        )
    assert "sum to 1.0" in str(exc.value)


def test_twin_of_requires_clean_variant():
    base = {
        "id": "T01c-x",
        "title": "t",
        "category": "communication",
        "difficulty": "easy",
        "prompt": "p",
        "twin_of": "T01-x",
    }
    clean = Task.model_validate({**base, "variant": "clean"})
    assert clean.twin_of == "T01-x"
    with pytest.raises(ValidationError) as exc:
        Task.model_validate(base)  # variant defaults to messy
    assert "clean-variant" in str(exc.value)
    with pytest.raises(ValidationError) as exc:
        Task.model_validate({**base, "variant": "clean", "twin_of": base["id"]})
    assert "not itself" in str(exc.value)


# --------------------------------------------------------------------------- #
# Readable failures on malformed YAML (Step 1 DoD)
# --------------------------------------------------------------------------- #
def test_malformed_task_fails_readably():
    with pytest.raises(SchemaError) as exc:
        load_task(FIXTURES / "task_malformed.yaml")
    message = str(exc.value)
    # Points at the file...
    assert "task_malformed.yaml" in message
    # ...and names the actual problems a human must fix.
    assert "category" in message
    assert "prompt" in message


def test_bad_weights_rubric_fails_readably():
    with pytest.raises(SchemaError) as exc:
        load_rubric(FIXTURES / "rubric_bad_weights.yaml")
    assert "sum to 1.0" in str(exc.value)


def test_task_rejects_unknown_field():
    # extra="forbid" catches typos in task.yaml keys.
    with pytest.raises(ValidationError) as exc:
        Task.model_validate(
            {
                "id": "x",
                "title": "t",
                "category": "communication",
                "difficulty": "easy",
                "prompt": "p",
                "typo_field": 1,
            }
        )
    assert "typo_field" in str(exc.value)


def test_missing_yaml_mapping_fails():
    empty = FIXTURES / "empty_list.yaml"
    empty.write_text("- just\n- a\n- list\n", encoding="utf-8")
    try:
        with pytest.raises(SchemaError):
            load_task(empty)
    finally:
        empty.unlink()


# --------------------------------------------------------------------------- #
# Criterion / anchor validation
# --------------------------------------------------------------------------- #
def test_anchors_must_be_1_3_5():
    bad = {
        "task_id": "T",
        "criteria": [
            {
                "name": "c",
                "weight": 1.0,
                "description": "d",
                "anchors": {1: "a", 2: "b"},  # 2 is not allowed; 3 and 5 missing
            }
        ],
    }
    with pytest.raises(ValidationError) as exc:
        Rubric.model_validate(bad)
    assert "1, 3 and 5" in str(exc.value)


def test_duplicate_criterion_names_rejected():
    dupe = {
        "task_id": "T",
        "criteria": [
            {"name": "c", "weight": 0.5, "description": "d", "anchors": {1: "a", 3: "b", 5: "c"}},
            {"name": "c", "weight": 0.5, "description": "d", "anchors": {1: "a", 3: "b", 5: "c"}},
        ],
    }
    with pytest.raises(ValidationError) as exc:
        Rubric.model_validate(dupe)
    assert "unique" in str(exc.value)


# --------------------------------------------------------------------------- #
# Content-hash versioning (fix #2)
# --------------------------------------------------------------------------- #
def test_task_hash_is_deterministic():
    assert hash_task_dir(GOOD_TASK_DIR) == hash_task_dir(GOOD_TASK_DIR)
    assert hash_task_dir(GOOD_TASK_DIR).startswith("sha256:")


def test_task_hash_changes_when_artifact_changes(tmp_path):
    clone = tmp_path / "task"
    shutil.copytree(GOOD_TASK_DIR, clone)
    before = hash_task_dir(clone)
    # Mutate an artifact's bytes.
    (clone / "artifacts" / "emails.md").write_text("different content\n", encoding="utf-8")
    after = hash_task_dir(clone)
    assert before != after


def test_task_hash_ignores_comment_reformatting(tmp_path):
    clone = tmp_path / "task"
    shutil.copytree(GOOD_TASK_DIR, clone)
    before = hash_task_dir(clone)
    # Append a YAML comment: semantically identical, so the hash must not move.
    yaml_path = clone / "task.yaml"
    yaml_path.write_text(
        yaml_path.read_text(encoding="utf-8") + "\n# a trailing comment\n", encoding="utf-8"
    )
    assert hash_task_dir(clone) == before


def test_missing_declared_artifact_raises(tmp_path):
    clone = tmp_path / "task"
    shutil.copytree(GOOD_TASK_DIR, clone)
    (clone / "artifacts" / "emails.md").unlink()
    with pytest.raises(SchemaError) as exc:
        hash_task_dir(clone)
    assert "emails.md" in str(exc.value)


def test_rubric_hash_deterministic_and_sensitive():
    rubric = load_rubric(GOOD_TASK_DIR / "rubric.yaml")
    h1 = hash_rubric(rubric)
    assert h1 == hash_rubric(GOOD_TASK_DIR / "rubric.yaml")
    # Change a weight distribution (still summing to 1) -> different hash.
    data = rubric.model_dump()
    data["criteria"][0]["weight"] = 0.5
    data["criteria"][1]["weight"] = 0.3
    data["criteria"][2]["weight"] = 0.2
    mutated = Rubric.model_validate(data)
    assert hash_rubric(mutated) != h1


# --------------------------------------------------------------------------- #
# RawResult + sampling params (fix #3)
# --------------------------------------------------------------------------- #
def _now() -> datetime:
    return datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)


def test_raw_result_defaults_to_vendor_default_sampling():
    r = RawResult(
        task_id="T00-fixture-triage",
        model_id="gemini/gemini-1.5-flash",
        run_index=0,
        output="hello",
        timestamp=_now(),
        task_hash="sha256:abc123abc123",
    )
    assert r.cost_usd == 0.0
    assert r.sampling.source == "vendor-default"
    assert r.sampling.temperature is None
    # Round-trips through JSON without loss.
    again = RawResult.model_validate_json(r.model_dump_json())
    assert again == r


def test_raw_result_records_explicit_sampling():
    r = RawResult(
        task_id="T",
        model_id="groq/llama-3.1-70b",
        run_index=2,
        output="x",
        timestamp=_now(),
        task_hash="sha256:deadbeef0000",
        sampling=SamplingParams(temperature=0.2, top_p=0.9, source="explicit"),
    )
    assert r.sampling.temperature == 0.2
    assert r.sampling.source == "explicit"


def test_raw_result_rejects_negative_tokens():
    with pytest.raises(ValidationError):
        RawResult(
            task_id="T",
            model_id="m",
            run_index=0,
            output="x",
            timestamp=_now(),
            task_hash="h",
            tokens_in=-1,
        )


# --------------------------------------------------------------------------- #
# Score contract
# --------------------------------------------------------------------------- #
def test_score_valid_and_bounded():
    s = Score(
        task_id="T00-fixture-triage",
        model_id="gemini/gemini-1.5-flash",
        run_index=0,
        criterion_scores=[
            CriterionScore(
                name="correct-decision", score=5, judge_rationale="Chose Monday, cited 16:10 note."
            ),
            CriterionScore(
                name="surfaces-contradictions", score=3, judge_rationale="Flagged QA conflict only."
            ),
        ],
        weighted_total=4.2,
        judge_model="held-out-judge",
        failure_modes=["dropped-constraint"],
        task_hash="sha256:abc123abc123",
        rubric_hash="sha256:def456def456",
        timestamp=_now(),
    )
    assert s.weighted_total == 4.2
    assert s.failure_modes == ["dropped-constraint"]


def test_score_rejects_out_of_range_criterion():
    with pytest.raises(ValidationError):
        CriterionScore(name="c", score=6, judge_rationale="too high")


def test_score_rejects_unknown_failure_mode():
    with pytest.raises(ValidationError):
        Score(
            task_id="T",
            model_id="m",
            run_index=0,
            criterion_scores=[CriterionScore(name="c", score=3, judge_rationale="ok")],
            weighted_total=3.0,
            judge_model="j",
            failure_modes=["not-a-real-mode"],
            task_hash="h",
            rubric_hash="r",
            timestamp=_now(),
        )


# --------------------------------------------------------------------------- #
# Record addressing
# --------------------------------------------------------------------------- #
def test_record_id_slugifies_model():
    assert record_id("T01", "gemini/gemini-1.5-flash", 3) == "T01__gemini-gemini-1.5-flash__run3"
    assert record_id("T01", "openrouter/deepseek:free", 0) == "T01__openrouter-deepseek-free__run0"


def test_categories_constant_matches_literal():
    # Guardrail: the CATEGORIES tuple and the Category Literal must stay in sync.
    import typing

    assert set(schemas.CATEGORIES) == set(typing.get_args(Category))
