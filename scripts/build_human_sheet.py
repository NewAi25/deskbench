#!/usr/bin/env python3
"""Build the blind human-grading sheet for the 48 pilot outputs (methodology §5).

Produces a single markdown sheet plus a machine manifest. For every raw result it
emits: task/model/run, the FULL model output, the task's rubric criteria with
their 1/3/5 anchor text inline, empty score cells, an auto-fail cell, a
silent/flagged cell (methodology §4), a free-notes cell, and a machine-readable
`grades` fill-block the ingest script parses.

BLIND BY CONSTRUCTION: this script reads ONLY results/raw/ and tasks/. It never
opens results/scores/, so the judge's scores and rationales cannot leak into the
sheet. The 48 entries are shuffled with a FIXED, RECORDED seed so they are not
grouped by model.

Usage:
    python scripts/build_human_sheet.py         # writes the sheet + manifest
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from deskbench import schemas

REPO = Path(__file__).resolve().parents[1]
RAW_DIR = REPO / "results" / "raw"
TASKS_DIR = REPO / "tasks"
OUT_DIR = REPO / "results" / "human"
SHEET = OUT_DIR / "GRADING_SHEET.md"
MANIFEST = OUT_DIR / "GRADING_SHEET.manifest.json"

# Fixed shuffle seed — recorded in the sheet and manifest for reproducibility.
SEED = 20260718

# A hard guard: this file must never reference the judge's scores.
assert "scores" not in str(RAW_DIR).split("results")[-1], "sheet must not read results/scores"


def load_raws() -> list[dict]:
    raws = []
    for p in sorted(RAW_DIR.glob("*.json")):
        raws.append(json.loads(p.read_text(encoding="utf-8")))
    return raws


def task_brief(task_id: str) -> str:
    """One reusable brief per task: prompt + materials + reference answer."""
    tdir = TASKS_DIR / task_id
    task = schemas.load_task(tdir / "task.yaml")
    parts = [f"### Task brief — `{task_id}` ({task.variant})\n", "**Prompt**\n"]
    parts += [task.prompt.strip(), ""]
    for name in task.artifacts:
        content = (tdir / "artifacts" / name).read_text(encoding="utf-8").rstrip()
        parts += [f"**Material — `{name}`**\n", "~~~", content, "~~~", ""]
    ref = (tdir / "reference.md").read_text(encoding="utf-8").strip()
    parts += [
        "**Reference answer** (one competent answer, for context — grade against "
        "the anchors, not against this)\n",
        ref,
        "",
    ]
    return "\n".join(parts)


def criteria_block(rubric: schemas.Rubric) -> str:
    lines = []
    for c in rubric.criteria:
        lines.append(f"- **{c.name}** — weight {c.weight}, {c.kind}. {c.description.strip()}")
        lines.append(f"    - **1:** {c.anchors[1].strip()}")
        lines.append(f"    - **3:** {c.anchors[3].strip()}")
        lines.append(f"    - **5:** {c.anchors[5].strip()}")
    return "\n".join(lines)


def fill_block(entry_id: str, rubric: schemas.Rubric) -> str:
    lines = ["```grades", f"entry: {entry_id}"]
    for c in rubric.criteria:
        lines.append(f"{c.name}: ")
    lines += ["auto_fail: ", "silent_or_flagged: ", "notes: ", "```"]
    return "\n".join(lines)


HEADER = """# DeskBench — Human Grading Sheet (blind)

**You are grading {n} model outputs by hand, blind to the judge's scores** (this
sheet was generated without ever reading `results/scores/`). Your grades validate
the judge (methodology §5); judge–human agreement is reported per criterion.

- Entries are shuffled with a **fixed seed = {seed}** (recorded in the manifest),
  so they are **not grouped by model**. Grade them top to bottom.
- The task prompt, materials, and a reference answer for each task are in the
  **Task briefs** section below. Read those four briefs once, then grade.

## How to fill this sheet

For every entry, edit ONLY its ```grades``` block:

1. **Criterion scores** — put an integer **1–5** after each criterion's colon,
   using that criterion's 1/3/5 anchors (listed inline under the entry). Use 2 or
   4 when the answer falls between anchors. Leave blank to mark "not yet graded".
2. **auto_fail** — `yes` or `no`. `yes` iff the output meets a rubric AUTO-FAIL
   condition (fabricates a figure/row/customer not in the inputs, or silently
   overwrites a value as certain fact). An auto-fail forces the weighted total to
   0 on ingest regardless of the criterion scores.
3. **silent_or_flagged** — `silent`, `flagged`, or `na`. Per methodology §4, an
   answer is **flagged** ONLY if it *explicitly signals uncertainty or requests
   verification on the specific point that is wrong* (generic hedging like
   "please double-check" does NOT count). If the answer is essentially correct
   with nothing wrong to classify, use `na`.
4. **notes** — free text on one line (optional).

Do not edit the `entry:` line, the anchors, or the outputs. When done, run:

    python scripts/ingest_human_grades.py

which parses these blocks (mapped via the manifest) into
`results/human/<task>__<model>__run<n>.json` records for the analyzer.

---

## Task briefs

{briefs}

---

## Entries ({n}, shuffled — seed {seed})
"""


def main() -> None:
    raws = load_raws()
    assert len(raws) == 48, f"expected 48 raw results, found {len(raws)}"

    # Reusable briefs (4 tasks), and cached rubrics + hashes per task.
    task_ids = sorted({r["task_id"] for r in raws})
    briefs = "\n".join(task_brief(t) for t in task_ids)
    rubrics = {t: schemas.load_rubric(TASKS_DIR / t / "rubric.yaml") for t in task_ids}
    thash = {t: schemas.hash_task_dir(TASKS_DIR / t) for t in task_ids}
    rhash = {t: schemas.hash_rubric(rubrics[t]) for t in task_ids}

    # Shuffle deterministically.
    order = list(range(len(raws)))
    random.Random(SEED).shuffle(order)

    entries_md = []
    manifest_entries = []
    for pos, idx in enumerate(order, start=1):
        r = raws[idx]
        eid = f"H{pos:02d}"
        tid = r["task_id"]
        rubric = rubrics[tid]
        output = (r.get("output") or "").rstrip() or "(the model produced no output)"
        entries_md.append(
            f"### Entry {pos:02d} — `{eid}`\n\n"
            f"**task:** `{tid}` ({r['variant']}) · **model:** `{r['model_id']}` · "
            f"**run:** {r['run_index']}  \n"
            f"_(prompt, materials, and reference are in the Task brief for `{tid}` above)_\n\n"
            f"**Model output:**\n\n~~~text\n{output}\n~~~\n\n"
            f"**Score each criterion 1–5 against its anchors:**\n\n"
            f"{criteria_block(rubric)}\n\n"
            f"**Fill this block:**\n\n{fill_block(eid, rubric)}\n\n---\n"
        )
        manifest_entries.append(
            {
                "entry_id": eid,
                "task_id": tid,
                "model_id": r["model_id"],
                "run_index": r["run_index"],
                "variant": r["variant"],
                "task_hash": thash[tid],
                "rubric_hash": rhash[tid],
                "criteria": [c.name for c in rubric.criteria],
            }
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sheet = HEADER.format(n=len(raws), seed=SEED, briefs=briefs) + "\n" + "\n".join(entries_md)
    SHEET.write_text(sheet, encoding="utf-8")
    MANIFEST.write_text(
        json.dumps(
            {"seed": SEED, "blind": True, "source": "results/raw", "entries": manifest_entries},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {SHEET.relative_to(REPO)}  ({len(sheet):,} bytes, {len(raws)} entries)")
    print(f"wrote {MANIFEST.relative_to(REPO)}  (seed {SEED})")


if __name__ == "__main__":
    main()
