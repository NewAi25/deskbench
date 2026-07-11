#!/usr/bin/env python3
"""Step 3 saturation probe: are the pilot tasks too easy?

BUILD_PLAN §3 mandates a saturation check before scaling the suite: run the pilot
tasks against two models and look at the score spread. If everything scores
≥4/5, the tasks don't discriminate and must be hardened before Step 6.

This is a *lightweight probe*, deliberately separate from the rigorous grader
(`deskbench/grader.py`, Step 5): it runs two models on both pilot tasks, asks the
held-out judge for per-criterion scores, and prints the spread. It needs provider
keys in the environment and makes live calls, so CI never runs it. Its pure
helpers (prompt assembly, judge-JSON parsing, weighting, the saturation verdict)
are unit-tested in ``tests/test_saturation.py`` without any network.

Usage:
    python scripts/saturation_check.py                 # gemini-flash + llama-3.3-70b
    python scripts/saturation_check.py --models gemini-flash deepseek-v3-free
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from deskbench import schemas
from deskbench.registry import load_registry
from deskbench.runner import build_prompt  # canonical artifact-inlining prompt builder
from deskbench.schemas import Rubric

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODELS = ["gemini-flash", "llama-3.3-70b"]
SATURATION_THRESHOLD = 4.0

__all__ = ["build_prompt"]  # re-exported so tests/callers can use sc.build_prompt


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested, no network)
# --------------------------------------------------------------------------- #
def build_judge_prompt(rubric: Rubric, reference: str, output: str) -> str:
    """Ask the judge for per-criterion 1/3/5-anchored scores as JSON."""
    lines = [
        "You are grading a candidate answer against a rubric. Score each",
        "criterion on the 1-5 scale using its anchors. Grade against the anchors,",
        "not similarity to the reference; valid alternative approaches are fine.",
        "",
        "RUBRIC:",
    ]
    for c in rubric.criteria:
        lines.append(f"- {c.name} (weight {c.weight}): {c.description.strip()}")
        for level in (1, 3, 5):
            lines.append(f"    {level}: {c.anchors[level].strip()}")
    lines += [
        "",
        "REFERENCE (one competent answer, for context only):",
        reference.strip(),
        "",
        "CANDIDATE ANSWER:",
        output.strip(),
        "",
        'Respond ONLY with JSON: {"scores": {"<criterion-name>": <1-5>, ...}}.',
    ]
    return "\n".join(lines)


def parse_judge_scores(text: str, rubric: Rubric) -> dict[str, int]:
    """Best-effort extraction of {criterion: score} from a judge reply."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON object found in judge reply")
    data = json.loads(match.group(0))
    scores = data.get("scores", data)
    valid_names = {c.name for c in rubric.criteria}
    out: dict[str, int] = {}
    for name, value in scores.items():
        if name in valid_names:
            out[name] = int(round(float(value)))
    missing = valid_names - set(out)
    if missing:
        raise ValueError(f"judge did not score: {sorted(missing)}")
    return out


def weighted_total(scores: dict[str, int], rubric: Rubric) -> float:
    """Weighted mean of per-criterion scores (1-5)."""
    return round(sum(scores[c.name] * c.weight for c in rubric.criteria), 3)


def is_saturated(totals: list[float], threshold: float = SATURATION_THRESHOLD) -> bool:
    """Saturated iff every (task, model) score is at or above the threshold."""
    return bool(totals) and all(t >= threshold for t in totals)


# --------------------------------------------------------------------------- #
# Live run (needs keys)
# --------------------------------------------------------------------------- #
def run(models: list[str], task_ids: list[str]) -> int:
    reg = load_registry(REPO_ROOT / "config" / "models.yaml")
    rows: list[tuple[str, str, float]] = []

    for task_id in task_ids:
        task_dir = REPO_ROOT / "tasks" / task_id
        task = schemas.load_task(task_dir / "task.yaml")
        rubric = schemas.load_rubric(task_dir / "rubric.yaml")
        reference = (task_dir / "reference.md").read_text(encoding="utf-8")
        task_hash = schemas.hash_task_dir(task_dir)
        prompt = build_prompt(task, task_dir)

        for model_id in models:
            answer = reg.complete(model_id, prompt, task_hash=task_hash, run_index=0).text
            judge_reply = reg.complete(
                reg.judge_id,
                build_judge_prompt(rubric, reference, answer),
                task_hash=task_hash,
                run_index=0,
            ).text
            scores = parse_judge_scores(judge_reply, rubric)
            total = weighted_total(scores, rubric)
            rows.append((task_id, model_id, total))
            print(f"{task_id:32s} {model_id:20s} -> {total:.2f}/5")

    totals = [t for _, _, t in rows]
    print("\nScore spread:")
    print(f"  min={min(totals):.2f}  max={max(totals):.2f}  n={len(totals)}")
    if is_saturated(totals):
        print(
            "\n⚠️  SATURATED: every score is ≥ "
            f"{SATURATION_THRESHOLD}/5. The pilot tasks do not discriminate — "
            "harden them (more ambiguity, dirtier data) before scaling."
        )
        return 2
    print("\nOK: scores are spread; the tasks discriminate.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="DeskBench Step 3 saturation probe")
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    ap.add_argument(
        "--tasks",
        nargs="+",
        default=["T01-inbox-triage", "T02-spreadsheet-reconciliation"],
    )
    args = ap.parse_args()
    return run(args.models, args.tasks)


if __name__ == "__main__":
    raise SystemExit(main())
