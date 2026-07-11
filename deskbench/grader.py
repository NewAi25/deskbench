"""Grader (Box 4): apply a rubric to a model output via the held-out LLM judge.

Given a task, its rubric + reference answer, and a model's output, the grader
asks the **judge** model (held out of the leaderboard — see registry fix #1 and
ADR-002) for per-criterion 1-5 scores with rationales, enforces a strict JSON
contract on the judge's reply, and returns a validated `Score`.

Guarantees:

* **Structured judge output, enforced.** The judge must return JSON scoring every
  rubric criterion. A malformed or incomplete reply is rejected and the judge is
  re-asked (`reject-and-retry`, up to `max_attempts`); persistent failure raises
  `GraderError` rather than emitting a fabricated score.
* **Grade against anchors, not the reference.** The judge prompt instructs the
  model to score against the rubric's 1/3/5 anchors and cite them; the reference
  is context only, so valid alternative approaches are not penalized.
* **Auto-fail is honored.** If the judge flags an auto-fail condition (e.g.
  fabricated data), the weighted total is forced to 0.0.

Failure-mode tagging (the taxonomy) is intentionally NOT done here — it is
human-assigned in Step 7 (ARCHITECTURE_REVIEW fix #5), so `Score.failure_modes`
is left empty by the grader.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from .registry import Registry
from .schemas import (
    CriterionScore,
    RawResult,
    Rubric,
    Score,
    Task,
    hash_rubric,
    load_rubric,
    load_task,
)

DEFAULT_SCORES_DIR = Path("results/scores")
DEFAULT_MAX_ATTEMPTS = 3


class JudgeParseError(ValueError):
    """The judge's reply did not conform to the required JSON contract."""


class GraderError(RuntimeError):
    """The judge could not produce a valid grade within the attempt budget."""


def _now() -> datetime:
    return datetime.now(UTC)


def build_judge_prompt(task: Task, rubric: Rubric, reference: str, output: str) -> str:
    """Construct the judge prompt: rubric anchors + reference (context) + output."""
    lines = [
        "You are an expert grader for a benchmark of realistic office work.",
        "Grade the CANDIDATE ANSWER against the RUBRIC below.",
        "",
        "Rules:",
        "- Score each criterion from 1 to 5 using its anchors; use 2 or 4 when the",
        "  answer falls between two anchors.",
        "- Grade against the ANCHORS, not similarity to the reference. A valid",
        "  alternative approach that meets an anchor must score well.",
        "- In each rationale, cite the specific anchor you matched. Do not grade on vibes.",
        "- The REFERENCE is one competent answer, provided for context only — it is",
        "  NOT the grading target.",
        "",
        "TASK PROMPT:",
        task.prompt.strip(),
        "",
        "RUBRIC:",
    ]
    for c in rubric.criteria:
        lines.append(f"[{c.name}] (weight {c.weight}) {c.description.strip()}")
        for level in (1, 3, 5):
            lines.append(f"    score {level}: {c.anchors[level].strip()}")
    if rubric.auto_fail:
        lines.append("")
        lines.append("AUTO-FAIL conditions (if ANY is met, set auto_fail.triggered = true):")
        for cond in rubric.auto_fail:
            lines.append(f"    - {cond}")
    lines += [
        "",
        "REFERENCE (context only, not the grading target):",
        reference.strip(),
        "",
        "CANDIDATE ANSWER:",
        output.strip() or "(the model produced no output)",
        "",
        "Respond with ONLY this JSON object and nothing else:",
        "{",
        '  "criteria": [',
        '    {"name": "<criterion-name>", "score": <1-5>, "rationale": "<cite the anchor>"}',
        "  ],",
        '  "auto_fail": {"triggered": <true|false>, "reason": "<short reason or empty>"}',
        "}",
    ]
    return "\n".join(lines)


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise JudgeParseError("no JSON object found in the judge reply")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise JudgeParseError(f"judge reply was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise JudgeParseError("judge JSON was not an object")
    return data


def parse_judge_response(
    text: str, rubric: Rubric
) -> tuple[list[CriterionScore], bool, str | None]:
    """Validate a judge reply into (criterion scores, auto_fail, reason).

    Raises :class:`JudgeParseError` if any criterion is missing, unknown,
    duplicated, out of range, or lacks a rationale.
    """
    data = _extract_json(text)
    entries = data.get("criteria")
    if not isinstance(entries, list):
        raise JudgeParseError("judge JSON has no 'criteria' list")

    valid_names = {c.name for c in rubric.criteria}
    scores: list[CriterionScore] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise JudgeParseError("each criterion entry must be an object")
        name = entry.get("name")
        if name not in valid_names:
            raise JudgeParseError(f"unknown or missing criterion name: {name!r}")
        if name in seen:
            raise JudgeParseError(f"duplicate criterion: {name!r}")
        seen.add(name)
        try:
            cs = CriterionScore(
                name=name,
                score=int(entry.get("score")),
                judge_rationale=str(entry.get("rationale", "")).strip(),
            )
        except (TypeError, ValueError) as exc:
            raise JudgeParseError(f"invalid score/rationale for {name!r}: {exc}") from exc
        scores.append(cs)

    missing = valid_names - seen
    if missing:
        raise JudgeParseError(f"judge omitted criteria: {sorted(missing)}")

    auto_fail = data.get("auto_fail") or {}
    triggered = bool(auto_fail.get("triggered", False))
    reason = auto_fail.get("reason") or None
    return scores, triggered, reason


def weighted_total(criterion_scores: list[CriterionScore], rubric: Rubric) -> float:
    """Weight-normalized mean of the per-criterion scores (1-5).

    Dividing by the weight sum keeps messy rubrics unchanged (their weights sum
    to 1.0) and puts clean rubrics — whose core-only weights sum to less than
    1.0 by design — on the same 1-5 scale, so twin totals stay comparable.
    """
    weights = {c.name: c.weight for c in rubric.criteria}
    weight_sum = sum(weights.values())
    return round(sum(cs.score * weights[cs.name] for cs in criterion_scores) / weight_sum, 3)


def grade(
    registry: Registry,
    *,
    task: Task,
    rubric: Rubric,
    reference: str,
    output: str,
    task_hash: str,
    model_id: str,
    run_index: int,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    use_cache: bool = True,
) -> Score:
    """Grade one model output with the held-out judge, reject-and-retry on parse."""
    rubric_hash = hash_rubric(rubric)
    prompt = build_judge_prompt(task, rubric, reference, output)
    # Judge cache seed encodes the exact candidate + rubric so grades of
    # different outputs never collide; run_index=attempt gives a fresh call on retry.
    seed = f"{task_hash}::grade::{model_id}::run{run_index}::{rubric_hash}"

    parsed: tuple[list[CriterionScore], bool, str | None] | None = None
    last_error: JudgeParseError | None = None
    for attempt in range(max_attempts):
        reply = registry.complete(
            registry.judge_id,
            prompt,
            task_hash=seed,
            run_index=attempt,
            use_cache=use_cache,
        ).text
        try:
            parsed = parse_judge_response(reply, rubric)
            break
        except JudgeParseError as exc:
            last_error = exc

    if parsed is None:
        raise GraderError(
            f"judge output failed to parse after {max_attempts} attempts: {last_error}"
        )

    criterion_scores, auto_fail_triggered, _reason = parsed
    total = 0.0 if auto_fail_triggered else weighted_total(criterion_scores, rubric)
    return Score(
        task_id=task.id,
        model_id=model_id,
        run_index=run_index,
        criterion_scores=criterion_scores,
        weighted_total=total,
        auto_fail_triggered=auto_fail_triggered,
        judge_model=registry.judge_id,
        failure_modes=[],  # human-assigned in Step 7 (fix #5)
        task_hash=task_hash,
        rubric_hash=rubric_hash,
        timestamp=_now(),
    )


def grade_raw_result(
    registry: Registry,
    raw: RawResult,
    task_dir: str | Path,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    use_cache: bool = True,
) -> Score:
    """Load a task's rubric + reference and grade a RawResult's output."""
    task_dir = Path(task_dir)
    task = load_task(task_dir / "task.yaml")
    rubric = load_rubric(task_dir / "rubric.yaml")
    reference = (task_dir / "reference.md").read_text(encoding="utf-8")
    return grade(
        registry,
        task=task,
        rubric=rubric,
        reference=reference,
        output=raw.output,
        task_hash=raw.task_hash,
        model_id=raw.model_id,
        run_index=raw.run_index,
        max_attempts=max_attempts,
        use_cache=use_cache,
    )
