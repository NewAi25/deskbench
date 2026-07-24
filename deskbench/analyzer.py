"""Analyzer (Box 6): aggregate judge scores + human grades into the pilot findings.

Reads the three evidence stores —

    results/raw/     (RawResult: variant, run metadata)
    results/scores/  (Score: the held-out judge's per-criterion grades)
    results/human/   (the maintainer's blind per-criterion grades + silent/flagged tags)

— and writes ``results/summary.json`` plus ``results/tables/*.csv`` containing
the four pilot findings and run variance:

* **leaderboard** — mean ``weighted_total`` per model, judge AND human, split
  messy/clean, with every per-run value listed (nothing hides in a mean).
* **mess_penalty** — per model per twin pair, CORE criteria only, using the
  relative-core-weight formula from methodology.md §3 (sign = clean − messy;
  positive means the mess degraded the model). Computed independently from
  judge scores and from human scores. Per-criterion scores, never a
  difference of weighted totals; auto-fail zeros therefore do not enter.
* **silent_failure** — per model, from the HUMAN silent/flagged tags only:
  silent / (silent + flagged), with ``na`` excluded and all counts reported.
* **agreement** — judge vs human: per-criterion Pearson r and MAE on the 1-5
  scores, exact-match rate on auto_fail, weighted-total correlation + MAE,
  and the largest weighted-total disagreements listed with record ids.
* **variance** — per model × task, across-run sample standard deviation of
  the weighted total (judge and human).

Every number is computed from files on disk; nothing is hand-entered. The
statistics helpers are pure functions, unit-tested on hand-computed fixtures
in ``tests/test_analyzer.py``.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .schemas import Rubric, Score, Task, load_rubric, load_task

DEFAULT_RAW_DIR = Path("results/raw")
DEFAULT_SCORES_DIR = Path("results/scores")
DEFAULT_HUMAN_DIR = Path("results/human")
DEFAULT_SUMMARY = Path("results/summary.json")
DEFAULT_TABLES_DIR = Path("results/tables")

TOP_DISAGREEMENTS = 10


class AnalyzerError(RuntimeError):
    """Raised when the evidence on disk is inconsistent with itself."""


# --------------------------------------------------------------------------- #
# Pure statistics helpers (unit-tested on hand-computed fixtures)
# --------------------------------------------------------------------------- #
def mean(xs: list[float]) -> float:
    if not xs:
        raise AnalyzerError("mean of empty list")
    return sum(xs) / len(xs)


def sample_std(xs: list[float]) -> float | None:
    """Sample standard deviation (ddof=1); None when n < 2."""
    if len(xs) < 2:
        return None
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson r; None when either side has zero variance (r is undefined)."""
    if len(xs) != len(ys):
        raise AnalyzerError(f"pearson: length mismatch {len(xs)} vs {len(ys)}")
    if len(xs) < 2:
        return None
    mx, my = mean(xs), mean(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    sxx = sum(d * d for d in dx)
    syy = sum(d * d for d in dy)
    if sxx == 0 or syy == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy, strict=True)) / math.sqrt(sxx * syy)


def mae(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or not xs:
        raise AnalyzerError(f"mae: bad lengths {len(xs)} vs {len(ys)}")
    return sum(abs(a - b) for a, b in zip(xs, ys, strict=True)) / len(xs)


def mess_penalty(
    clean_by_criterion: dict[str, list[float]],
    messy_by_criterion: dict[str, list[float]],
    core_weights: dict[str, float],
) -> float:
    """Methodology §3: Σ_core w_rel(c) · (mean clean(c) − mean messy(c)).

    ``core_weights`` are the shared core weights (identical across the twin
    pair); they are normalized to relative weights here. Positive result =
    the mess degraded the model.
    """
    wsum = sum(core_weights.values())
    if wsum <= 0:
        raise AnalyzerError("mess_penalty: core weights sum to zero")
    missing = [c for c in core_weights if c not in clean_by_criterion or not clean_by_criterion[c]]
    missing += [c for c in core_weights if c not in messy_by_criterion or not messy_by_criterion[c]]
    if missing:
        raise AnalyzerError(f"mess_penalty: no scores for core criteria {sorted(set(missing))}")
    return sum(
        (w / wsum) * (mean(clean_by_criterion[c]) - mean(messy_by_criterion[c]))
        for c, w in core_weights.items()
    )


def silent_failure_stats(tags: list[bool | None]) -> dict[str, Any]:
    """Counts + rate from human silent(True)/flagged(False)/na(None) tags."""
    silent = sum(1 for t in tags if t is True)
    flagged = sum(1 for t in tags if t is False)
    na = sum(1 for t in tags if t is None)
    denom = silent + flagged
    return {
        "silent": silent,
        "flagged": flagged,
        "na_excluded": na,
        "rate": round(silent / denom, 3) if denom else None,
    }


# --------------------------------------------------------------------------- #
# Evidence loading
# --------------------------------------------------------------------------- #
def _load_tasks(tasks_dir: Path) -> dict[str, Task]:
    tasks: dict[str, Task] = {}
    for d in sorted(tasks_dir.iterdir()):
        if d.is_dir() and (d / "task.yaml").exists():
            t = load_task(d / "task.yaml")
            tasks[t.id] = t
    return tasks


def _load_rubrics(tasks_dir: Path, tasks: dict[str, Task]) -> dict[str, Rubric]:
    return {tid: load_rubric(tasks_dir / tid / "rubric.yaml") for tid in tasks}


def _load_scores(scores_dir: Path) -> dict[tuple[str, str, int], Score]:
    out: dict[tuple[str, str, int], Score] = {}
    for p in sorted(scores_dir.glob("*.json")):
        s = Score.model_validate_json(p.read_text(encoding="utf-8"))
        out[(s.task_id, s.model_id, s.run_index)] = s
    return out


def _load_human(human_dir: Path) -> dict[tuple[str, str, int], dict[str, Any]]:
    out: dict[tuple[str, str, int], dict[str, Any]] = {}
    for p in sorted(human_dir.glob("*.json")):
        if p.name.startswith("GRADING_SHEET"):
            continue
        h = json.loads(p.read_text(encoding="utf-8"))
        if h.get("grader") != "human":
            raise AnalyzerError(f"{p}: not a human grade record")
        out[(h["task_id"], h["model_id"], h["run_index"])] = h
    return out


def _crit_scores(record: Score | dict[str, Any]) -> dict[str, int]:
    if isinstance(record, Score):
        return {cs.name: cs.score for cs in record.criterion_scores}
    return {cs["name"]: cs["score"] for cs in record["criterion_scores"]}


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def analyze(
    tasks_dir: Path = Path("tasks"),
    raw_dir: Path = DEFAULT_RAW_DIR,
    scores_dir: Path = DEFAULT_SCORES_DIR,
    human_dir: Path = DEFAULT_HUMAN_DIR,
) -> dict[str, Any]:
    """Compute the full summary dict from the evidence on disk."""
    tasks = _load_tasks(tasks_dir)
    rubrics = _load_rubrics(tasks_dir, tasks)
    scores = _load_scores(scores_dir)
    human = _load_human(human_dir)

    if not scores:
        raise AnalyzerError(f"no score records in {scores_dir}")
    if not human:
        raise AnalyzerError(f"no human records in {human_dir}")

    models = sorted({k[1] for k in scores})
    variant_of = {tid: t.variant for tid, t in tasks.items()}
    twin_pairs = [
        (t.twin_of, tid) for tid, t in sorted(tasks.items()) if t.variant == "clean" and t.twin_of
    ]
    judge_models = sorted({s.judge_model for s in scores.values()})

    # ---------------- leaderboard (a) ---------------- #
    leaderboard: list[dict[str, Any]] = []
    for m in models:
        row: dict[str, Any] = {"model": m}
        for source, records in (("judge", scores), ("human", human)):
            runs = []
            for (tid, mid, run), rec in sorted(records.items()):
                if mid != m:
                    continue
                wt = rec.weighted_total if isinstance(rec, Score) else rec["weighted_total"]
                af = (
                    rec.auto_fail_triggered
                    if isinstance(rec, Score)
                    else rec["auto_fail_triggered"]
                )
                runs.append(
                    {
                        "task_id": tid,
                        "variant": variant_of[tid],
                        "run_index": run,
                        "weighted_total": wt,
                        "auto_fail": af,
                    }
                )
            overall = [r["weighted_total"] for r in runs]
            messy = [r["weighted_total"] for r in runs if r["variant"] == "messy"]
            clean = [r["weighted_total"] for r in runs if r["variant"] == "clean"]
            row[source] = {
                "mean_overall": round(mean(overall), 3) if overall else None,
                "mean_messy": round(mean(messy), 3) if messy else None,
                "mean_clean": round(mean(clean), 3) if clean else None,
                "n_runs": len(runs),
                "auto_fails": sum(1 for r in runs if r["auto_fail"]),
                "per_run": runs,
            }
        leaderboard.append(row)
    leaderboard.sort(key=lambda r: -(r["judge"]["mean_overall"] or 0))

    # ---------------- mess penalty (b) ---------------- #
    penalty_rows: list[dict[str, Any]] = []
    for m in models:
        for messy_id, clean_id in twin_pairs:
            core_weights = {
                c.name: c.weight for c in rubrics[messy_id].criteria if c.kind == "core"
            }
            row = {"model": m, "pair": messy_id, "clean_task": clean_id}
            for source, records in (("judge", scores), ("human", human)):
                by_crit: dict[str, dict[str, list[float]]] = {"messy": {}, "clean": {}}
                for (tid, mid, _run), rec in records.items():
                    if mid != m or tid not in (messy_id, clean_id):
                        continue
                    side = "messy" if tid == messy_id else "clean"
                    for name, sc in _crit_scores(rec).items():
                        if name in core_weights:
                            by_crit[side].setdefault(name, []).append(sc)
                row[source] = round(
                    mess_penalty(by_crit["clean"], by_crit["messy"], core_weights), 3
                )
            penalty_rows.append(row)
    # Per-model mean across pairs (equal pair weighting), per source.
    penalty_by_model = [
        {
            "model": m,
            "judge": round(mean([r["judge"] for r in penalty_rows if r["model"] == m]), 3),
            "human": round(mean([r["human"] for r in penalty_rows if r["model"] == m]), 3),
        }
        for m in models
    ]

    # ---------------- silent-failure rate (c) — HUMAN tags only ------------- #
    silent_rows = []
    for m in models:
        tags = [h["silent_failure"] for (_t, mid, _r), h in human.items() if mid == m]
        silent_rows.append({"model": m, **silent_failure_stats(tags)})

    # ---------------- judge–human agreement (d) ---------------- #
    paired_keys = sorted(set(scores) & set(human))
    unpaired = sorted(set(scores) ^ set(human))
    # Per-criterion, pooled across records that carry the criterion.
    crit_pairs: dict[str, tuple[list[float], list[float]]] = {}
    wt_j: list[float] = []
    wt_h: list[float] = []
    af_match = 0
    disagreements = []
    for key in paired_keys:
        s, h = scores[key], human[key]
        js, hs = _crit_scores(s), _crit_scores(h)
        if set(js) != set(hs):
            raise AnalyzerError(f"{key}: judge and human grade different criteria sets")
        for name in js:
            crit_pairs.setdefault(name, ([], []))
            crit_pairs[name][0].append(js[name])
            crit_pairs[name][1].append(hs[name])
        wt_j.append(s.weighted_total)
        wt_h.append(h["weighted_total"])
        if s.auto_fail_triggered == h["auto_fail_triggered"]:
            af_match += 1
        disagreements.append(
            {
                "record": f"{key[0]}__{key[1]}__run{key[2]}",
                "judge_total": s.weighted_total,
                "human_total": h["weighted_total"],
                "abs_diff": round(abs(s.weighted_total - h["weighted_total"]), 3),
                "judge_auto_fail": s.auto_fail_triggered,
                "human_auto_fail": h["auto_fail_triggered"],
            }
        )
    disagreements.sort(key=lambda d: -d["abs_diff"])
    per_criterion = [
        {
            "criterion": name,
            "n": len(js),
            "pearson_r": (None if (r := pearson(js, hs)) is None else round(r, 3)),
            "mae": round(mae(js, hs), 3),
        }
        for name, (js, hs) in sorted(crit_pairs.items())
    ]
    agreement = {
        "n_paired": len(paired_keys),
        "n_unpaired": len(unpaired),
        "unpaired_records": [f"{k[0]}__{k[1]}__run{k[2]}" for k in unpaired],
        "per_criterion": per_criterion,
        "weighted_total_pearson_r": (None if (r := pearson(wt_j, wt_h)) is None else round(r, 3)),
        "weighted_total_mae": round(mae(wt_j, wt_h), 3),
        "auto_fail_exact_match_rate": round(af_match / len(paired_keys), 3),
        "top_disagreements": disagreements[:TOP_DISAGREEMENTS],
    }

    # ---------------- variance (e) ---------------- #
    variance_rows = []
    for m in models:
        for tid in sorted(tasks):
            jt = [s.weighted_total for (t, mid, _r), s in scores.items() if mid == m and t == tid]
            ht = [h["weighted_total"] for (t, mid, _r), h in human.items() if mid == m and t == tid]
            if not jt and not ht:
                continue
            js = sample_std(jt)
            hs = sample_std(ht)
            variance_rows.append(
                {
                    "model": m,
                    "task_id": tid,
                    "variant": variant_of[tid],
                    "n_runs": len(jt),
                    "judge_std": None if js is None else round(js, 3),
                    "human_std": None if hs is None else round(hs, 3),
                }
            )

    n_raw = len(list(raw_dir.glob("*.json")))
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "matrix": {
            "tasks": sorted(tasks),
            "twin_pairs": [{"messy": a, "clean": b} for a, b in twin_pairs],
            "models": models,
            "judge_models": judge_models,
            "n_raw": n_raw,
            "n_judge_scores": len(scores),
            "n_human_grades": len(human),
        },
        "leaderboard": leaderboard,
        "mess_penalty": {"per_pair": penalty_rows, "per_model": penalty_by_model},
        "silent_failure": silent_rows,
        "agreement": agreement,
        "variance": variance_rows,
    }


# --------------------------------------------------------------------------- #
# Output writing
# --------------------------------------------------------------------------- #
def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(
    summary: dict[str, Any],
    summary_path: Path = DEFAULT_SUMMARY,
    tables_dir: Path = DEFAULT_TABLES_DIR,
) -> list[Path]:
    """Write summary.json and the CSV tables; return the written paths."""
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    written = [summary_path]

    lb_rows = [
        {
            "model": r["model"],
            "judge_overall": r["judge"]["mean_overall"],
            "judge_messy": r["judge"]["mean_messy"],
            "judge_clean": r["judge"]["mean_clean"],
            "human_overall": r["human"]["mean_overall"],
            "human_messy": r["human"]["mean_messy"],
            "human_clean": r["human"]["mean_clean"],
            "judge_auto_fails": r["judge"]["auto_fails"],
            "human_auto_fails": r["human"]["auto_fails"],
            "n_runs": r["judge"]["n_runs"],
        }
        for r in summary["leaderboard"]
    ]
    run_rows = [
        {
            "model": r["model"],
            "source": source,
            "task_id": run["task_id"],
            "variant": run["variant"],
            "run_index": run["run_index"],
            "weighted_total": run["weighted_total"],
            "auto_fail": run["auto_fail"],
        }
        for r in summary["leaderboard"]
        for source in ("judge", "human")
        for run in r[source]["per_run"]
    ]
    tables = {
        "leaderboard.csv": lb_rows,
        "runs.csv": run_rows,
        "mess_penalty_per_pair.csv": summary["mess_penalty"]["per_pair"],
        "mess_penalty_per_model.csv": summary["mess_penalty"]["per_model"],
        "silent_failure.csv": summary["silent_failure"],
        "agreement_per_criterion.csv": summary["agreement"]["per_criterion"],
        "disagreements.csv": summary["agreement"]["top_disagreements"],
        "variance.csv": summary["variance"],
    }
    for name, rows in tables.items():
        path = tables_dir / name
        _write_csv(path, rows)
        written.append(path)
    return written
