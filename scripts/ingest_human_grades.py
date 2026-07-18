#!/usr/bin/env python3
"""Ingest the filled human-grading sheet into results/human/*.json records.

Parses the ```grades``` blocks in results/human/GRADING_SHEET.md, maps each
`entry:` id to its (task, model, run) via GRADING_SHEET.manifest.json, validates
the scores, computes the weight-normalized total exactly as the judge grader does
(auto-fail forces 0.0), and writes one record per fully-graded entry:

    results/human/<task>__<model>__run<n>.json

These records mirror the judge Score records (results/scores/*.json) closely
enough for the Step-8 analyzer to pair them by (task_id, model_id, run_index) and
report judge–human agreement. Entries left blank are skipped (reported); entries
partially filled are reported as errors and NOT written.

Usage:
    python scripts/ingest_human_grades.py
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from deskbench import schemas

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "results" / "human"
SHEET = OUT_DIR / "GRADING_SHEET.md"
MANIFEST = OUT_DIR / "GRADING_SHEET.manifest.json"
TASKS_DIR = REPO / "tasks"

_YES = {"yes", "y", "true", "1"}
_NO = {"no", "n", "false", "0"}
_BLOCK = re.compile(r"```grades\s*\n(.*?)\n```", re.DOTALL)


def parse_blocks(text: str) -> list[dict[str, str]]:
    blocks = []
    for m in _BLOCK.finditer(text):
        kv: dict[str, str] = {}
        for line in m.group(1).splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            kv[k.strip()] = v.strip()
        blocks.append(kv)
    return blocks


def weighted_total(scores: dict[str, int], rubric: schemas.Rubric) -> float:
    weights = {c.name: c.weight for c in rubric.criteria}
    wsum = sum(weights.values())
    return round(sum(scores[n] * weights[n] for n in scores) / wsum, 3)


def main() -> None:
    if not SHEET.exists() or not MANIFEST.exists():
        raise SystemExit(f"missing {SHEET} or {MANIFEST}; run build_human_sheet.py first")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_entry = {e["entry_id"]: e for e in manifest["entries"]}
    seed = manifest["seed"]
    rubrics = {
        e["task_id"]: schemas.load_rubric(TASKS_DIR / e["task_id"] / "rubric.yaml")
        for e in manifest["entries"]
    }

    blocks = parse_blocks(SHEET.read_text(encoding="utf-8"))
    written = skipped_blank = errors = 0
    problems: list[str] = []

    for kv in blocks:
        eid = kv.get("entry", "")
        meta = by_entry.get(eid)
        if meta is None:
            errors += 1
            problems.append(f"{eid or '<no entry>'}: not in manifest")
            continue
        crit_names = meta["criteria"]
        rubric = rubrics[meta["task_id"]]

        raw_scores = {n: kv.get(n, "").strip() for n in crit_names}
        af = kv.get("auto_fail", "").strip().lower()
        sf = kv.get("silent_or_flagged", "").strip().lower()
        filled = [v for v in raw_scores.values() if v] + ([af] if af else []) + ([sf] if sf else [])

        if not filled:
            skipped_blank += 1
            continue
        # Partially filled -> report, do not write.
        missing = [n for n, v in raw_scores.items() if not v]
        if missing or not af or not sf:
            errors += 1
            miss = missing + ([] if af else ["auto_fail"]) + ([] if sf else ["silent_or_flagged"])
            problems.append(f"{eid}: incomplete (missing: {', '.join(miss)})")
            continue

        # Validate scores.
        try:
            scores = {n: int(raw_scores[n]) for n in crit_names}
        except ValueError:
            errors += 1
            problems.append(f"{eid}: non-integer score in {raw_scores}")
            continue
        if any(not 1 <= s <= 5 for s in scores.values()):
            errors += 1
            problems.append(f"{eid}: score out of range 1-5 in {scores}")
            continue
        if af in _YES:
            auto_fail = True
        elif af in _NO:
            auto_fail = False
        else:
            errors += 1
            problems.append(f"{eid}: auto_fail must be yes/no, got {af!r}")
            continue
        if sf == "silent":
            silent_failure: bool | None = True
        elif sf == "flagged":
            silent_failure = False
        elif sf in {"na", "n/a", "none", "-"}:
            silent_failure = None
        else:
            errors += 1
            problems.append(f"{eid}: silent_or_flagged must be silent/flagged/na, got {sf!r}")
            continue

        total = 0.0 if auto_fail else weighted_total(scores, rubric)
        record = {
            "task_id": meta["task_id"],
            "model_id": meta["model_id"],
            "run_index": meta["run_index"],
            "variant": meta["variant"],
            "grader": "human",
            "entry_id": eid,
            "criterion_scores": [{"name": n, "score": scores[n]} for n in crit_names],
            "weighted_total": total,
            "auto_fail_triggered": auto_fail,
            "silent_failure": silent_failure,
            "notes": kv.get("notes", "").strip(),
            "task_hash": meta["task_hash"],
            "rubric_hash": meta["rubric_hash"],
            "seed": seed,
            "graded_at": datetime.now(UTC).isoformat(),
        }
        stem = schemas.record_id(meta["task_id"], meta["model_id"], meta["run_index"])
        (OUT_DIR / f"{stem}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        written += 1

    print(f"ingested {written} record(s) -> results/human/")
    print(f"skipped {skipped_blank} blank (not yet graded); {errors} error(s)")
    for p in problems:
        print(f"  ! {p}")
    if written:
        print(f"\n{written}/48 graded. Re-run after filling more; records overwrite cleanly.")


if __name__ == "__main__":
    main()
