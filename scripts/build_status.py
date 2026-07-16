#!/usr/bin/env python3
"""Auto-update the status table in BUILDSEQUENCE.md from machine-checked DoD.

A step is marked ``done`` only when its artifacts actually exist on disk and its
test module actually passes. A step whose predecessor is done but whose own
checks only partially pass is ``in progress``; everything else is ``pending``.
No commit-message parsing, no honor system: the table is a pure function of the
repository's real state, so any reviewer can reproduce it by running this script.

Run from anywhere:  ``python scripts/build_status.py``

Exit code is 0 whether or not the table changed; it prints what it did. The
``build-status`` GitHub workflow runs this and, if BUILDSEQUENCE.md changed,
commits it back with ``[skip ci]`` so the push does not retrigger CI.

This module is import-safe and unit-tested by ``tests/test_build_status.py``.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SEQUENCE_FILE = REPO_ROOT / "BUILDSEQUENCE.md"

BEGIN_MARKER = "<!-- STATUS:BEGIN"
END_MARKER = "<!-- STATUS:END"

# Status glyphs — must match the legend in BUILDSEQUENCE.md exactly.
PENDING = "⬜ pending"
IN_PROGRESS = "🟨 in progress"
DONE = "✅ done"

# MVP pilot matrix: 2 tasks × 2 variants × 4 models × 3 runs.
PILOT_EXPECTED_RUNS = 48


@dataclass
class Step:
    """One build step and the machine-checkable conditions that certify it."""

    number: int
    #: Repo-relative paths that must all exist.
    files: list[str] = field(default_factory=list)
    #: Test modules (repo-relative) that must pass under pytest.
    tests: list[str] = field(default_factory=list)
    #: Extra predicate names (resolved to functions below), all must return True.
    extra: list[str] = field(default_factory=list)


# The DoD encoded here mirrors the human-readable DoD column in BUILDSEQUENCE.md.
STEPS: list[Step] = [
    Step(0, files=["pyproject.toml", "README.md", ".env.example", ".github/workflows/ci.yml"]),
    Step(
        1,
        files=["deskbench/schemas.py"],
        tests=["tests/test_schemas.py"],
        extra=["schemas_define_contracts"],
    ),
    Step(
        2,
        files=["config/models.yaml", "deskbench/registry.py"],
        tests=["tests/test_registry.py"],
        extra=["models_yaml_has_four"],
    ),
    Step(3, extra=["pilot_tasks_validate", "saturation_recorded"]),
    Step(
        4,
        files=["deskbench/runner.py"],
        tests=["tests/test_runner.py"],
        extra=["raw_fixture_exists"],
    ),
    Step(
        5,
        files=["deskbench/grader.py"],
        tests=["tests/test_grader.py"],
        extra=["score_fixture_exists"],
    ),
    Step(6, tests=["tests/test_tasks.py"], extra=["twin_suite_validates"]),
    Step(7, extra=["pilot_run_complete"]),
    Step(8, extra=["human_grades_ingested", "summary_mvp_complete"]),
    Step(9, files=["site/index.html"], extra=["dashboard_embeds_data"]),
    Step(10, files=["report/REPORT.md"], extra=["report_has_caveats"]),
]


# --------------------------------------------------------------------------- #
# Primitive checks
# --------------------------------------------------------------------------- #
def _exists(root: Path, rel: str) -> bool:
    return (root / rel).exists()


def _run_pytest(root: Path, rel: str) -> bool:
    """Return True if the given test module passes (or is a no-op collection)."""
    target = root / rel
    if not target.exists():
        return False
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(target), "-q"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _source_defines(root: Path, rel: str, symbols: list[str]) -> bool:
    path = root / rel
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    return all(re.search(rf"^\s*class\s+{re.escape(s)}\b", text, re.M) for s in symbols)


# --------------------------------------------------------------------------- #
# Extra predicates (referenced by name in STEPS[*].extra)
# --------------------------------------------------------------------------- #
def schemas_define_contracts(root: Path) -> bool:
    return _source_defines(root, "deskbench/schemas.py", ["Task", "Rubric", "RawResult", "Score"])


def models_yaml_has_four(root: Path) -> bool:
    path = root / "config" / "models.yaml"
    if not path.exists():
        return False
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    models = data.get("models", data if isinstance(data, list) else [])
    return isinstance(models, list) and len(models) >= 4


def _task_dirs(root: Path) -> list[Path]:
    tasks = root / "tasks"
    if not tasks.exists():
        return []
    return sorted(p for p in tasks.iterdir() if p.is_dir() and (p / "task.yaml").exists())


def _task_dir_valid(task_dir: Path) -> bool:
    required = ["task.yaml", "rubric.yaml", "reference.md"]
    if not all((task_dir / f).exists() for f in required):
        return False
    if not (task_dir / "artifacts").is_dir():
        return False
    try:
        from deskbench import schemas

        schemas.load_task(task_dir / "task.yaml")
        schemas.load_rubric(task_dir / "rubric.yaml")
    except Exception:
        return False
    return True


def pilot_tasks_validate(root: Path) -> bool:
    dirs = _task_dirs(root)
    valid = [d for d in dirs if _task_dir_valid(d)]
    return len(valid) >= 2


def saturation_recorded(root: Path) -> bool:
    """Step 3 DoD: BUILD_LOG records an actual saturation result, not a promise.

    The convention (documented in BUILDSEQUENCE.md): after running
    scripts/saturation_check.py, the maintainer records a BUILD_LOG line
    starting ``SATURATION RESULT:``. Added 2026-07-16 per the audit's F3 — the
    predicate was weaker than the DoD text, which let Step 3 flip done without
    the check ever running.
    """
    log = root / "BUILD_LOG.md"
    if not log.exists():
        return False
    return bool(re.search(r"^SATURATION RESULT:", log.read_text(encoding="utf-8"), re.M))


def twin_suite_validates(root: Path) -> bool:
    """MVP step 6: ≥4 valid task dirs forming ≥2 clean/messy twin pairs."""
    dirs = _task_dirs(root)
    valid = [d for d in dirs if _task_dir_valid(d)]
    if len(valid) < 4:
        return False
    try:
        from deskbench import schemas

        tasks = [schemas.load_task(d / "task.yaml") for d in valid]
    except Exception:
        return False
    by_id = {t.id: t for t in tasks}
    clean = [t for t in tasks if t.variant == "clean"]
    if len(clean) < 2:
        return False
    return all(t.twin_of in by_id and by_id[t.twin_of].variant == "messy" for t in clean)


def raw_fixture_exists(root: Path) -> bool:
    return any((root / "tests" / "fixtures").glob("*raw*.json")) or any(
        (root / "results" / "raw").glob("*.json")
    )


def score_fixture_exists(root: Path) -> bool:
    return any((root / "tests" / "fixtures").glob("*score*.json")) or any(
        (root / "results" / "scores").glob("*.json")
    )


def pilot_run_complete(root: Path) -> bool:
    """MVP step 7: the full 48-run matrix exists, raw and judge-scored."""
    raw = list((root / "results" / "raw").glob("*.json"))
    scores = list((root / "results" / "scores").glob("*.json"))
    return len(raw) >= PILOT_EXPECTED_RUNS and len(scores) >= PILOT_EXPECTED_RUNS


def human_grades_ingested(root: Path) -> bool:
    """MVP step 8a: the 100% human grading sheet has been filled and ingested."""
    human = root / "results" / "human"
    return human.is_dir() and any(p.is_file() and p.name != ".gitkeep" for p in human.iterdir())


def summary_mvp_complete(root: Path) -> bool:
    """MVP step 8b: summary.json reports the four pilot findings + variance."""
    summary = root / "results" / "summary.json"
    if not summary.exists():
        return False
    text = summary.read_text(encoding="utf-8")
    keys = ("leaderboard", "mess_penalty", "silent_failure", "agreement", "variance")
    return all(k in text for k in keys)


def dashboard_embeds_data(root: Path) -> bool:
    path = root / "site" / "index.html"
    return path.exists() and "summary" in path.read_text(encoding="utf-8", errors="ignore").lower()


def report_has_caveats(root: Path) -> bool:
    path = root / "report" / "REPORT.md"
    if not path.exists():
        return False
    return "do not show" in path.read_text(encoding="utf-8").lower().replace("does not", "do not")


_PREDICATES = {
    "schemas_define_contracts": schemas_define_contracts,
    "models_yaml_has_four": models_yaml_has_four,
    "pilot_tasks_validate": pilot_tasks_validate,
    "saturation_recorded": saturation_recorded,
    "raw_fixture_exists": raw_fixture_exists,
    "score_fixture_exists": score_fixture_exists,
    "twin_suite_validates": twin_suite_validates,
    "pilot_run_complete": pilot_run_complete,
    "human_grades_ingested": human_grades_ingested,
    "summary_mvp_complete": summary_mvp_complete,
    "dashboard_embeds_data": dashboard_embeds_data,
    "report_has_caveats": report_has_caveats,
}


# --------------------------------------------------------------------------- #
# Status computation
# --------------------------------------------------------------------------- #
def evaluate_step(step: Step, root: Path, run_tests: bool = True) -> tuple[bool, bool]:
    """Return (all_checks_pass, any_check_passes) for one step."""
    results: list[bool] = []
    for rel in step.files:
        results.append(_exists(root, rel))
    for rel in step.tests:
        results.append(_run_pytest(root, rel) if run_tests else _exists(root, rel))
    for name in step.extra:
        try:
            results.append(bool(_PREDICATES[name](root)))
        except Exception:
            results.append(False)
    if not results:
        return (False, False)
    return (all(results), any(results))


def compute_statuses(root: Path = REPO_ROOT, run_tests: bool = True) -> dict[int, str]:
    """Map each step number to its status glyph, honoring ordering."""
    statuses: dict[int, str] = {}
    prev_done = True
    for step in STEPS:
        all_ok, any_ok = evaluate_step(step, root, run_tests=run_tests)
        if all_ok:
            status = DONE
        elif prev_done and any_ok:
            status = IN_PROGRESS
        else:
            status = PENDING
        statuses[step.number] = status
        prev_done = status == DONE
    return statuses


# --------------------------------------------------------------------------- #
# Table rendering
# --------------------------------------------------------------------------- #
_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|")


def render(text: str, statuses: dict[int, str]) -> str:
    """Rewrite the Status column of each step row between the STATUS markers."""
    lines = text.splitlines(keepends=False)
    inside = False
    out: list[str] = []
    for line in lines:
        if BEGIN_MARKER in line:
            inside = True
            out.append(line)
            continue
        if END_MARKER in line:
            inside = False
            out.append(line)
            continue
        if inside:
            m = _ROW_RE.match(line)
            if m:
                step_num = int(m.group(1))
                if step_num in statuses:
                    cells = line.split("|")
                    # cells[-1] is trailing empty (line ends with "|"); status is cells[-2].
                    cells[-2] = f" {statuses[step_num]} "
                    line = "|".join(cells)
        out.append(line)
    trailing = "\n" if text.endswith("\n") else ""
    return "\n".join(out) + trailing


def main() -> int:
    if not SEQUENCE_FILE.exists():
        print(f"error: {SEQUENCE_FILE} not found", file=sys.stderr)
        return 1
    original = SEQUENCE_FILE.read_text(encoding="utf-8")
    statuses = compute_statuses(REPO_ROOT)
    updated = render(original, statuses)
    # Use the word (not the emoji glyph) so stdout is safe on legacy consoles.
    summary = ", ".join(f"{n}:{s.split()[-1]}" for n, s in sorted(statuses.items()))
    if updated != original:
        SEQUENCE_FILE.write_text(updated, encoding="utf-8", newline="\n")
        print(f"build status updated -> {summary}")
    else:
        print(f"build status unchanged -> {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
