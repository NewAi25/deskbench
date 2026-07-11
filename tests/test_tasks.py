"""Schema-validate every authored task directory in the suite.

Per BUILD_PLAN §3, CI schema-validates all tasks on push. This walks tasks/ and
asserts each directory is a well-formed task: task.yaml + rubric.yaml validate,
the rubric's task_id matches, every declared artifact exists, there is a
reference.md, and the content hash computes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deskbench import schemas

TASKS_DIR = Path(__file__).resolve().parents[1] / "tasks"


def _task_dirs() -> list[Path]:
    if not TASKS_DIR.exists():
        return []
    return sorted(p for p in TASKS_DIR.iterdir() if p.is_dir() and (p / "task.yaml").exists())


TASK_DIRS = _task_dirs()


def test_pilot_tasks_exist():
    ids = {p.name for p in TASK_DIRS}
    assert {
        "T01-inbox-triage",
        "T02-spreadsheet-reconciliation",
        "T01c-inbox-triage",
        "T02c-spreadsheet-reconciliation",
    }.issubset(ids)


@pytest.mark.parametrize("task_dir", TASK_DIRS, ids=[p.name for p in TASK_DIRS])
def test_task_dir_is_valid(task_dir: Path):
    task = schemas.load_task(task_dir / "task.yaml")
    rubric = schemas.load_rubric(task_dir / "rubric.yaml")

    # The task id should match the directory name (content-addressing invariant).
    assert task.id == task_dir.name
    # The rubric must be for this task.
    assert rubric.task_id == task.id
    # A reference answer must exist (authored before any model run).
    assert (task_dir / "reference.md").is_file()
    # Every declared artifact must be present.
    for name in task.artifacts:
        assert (task_dir / "artifacts" / name).is_file(), f"missing artifact {name}"
    # The content hash computes (this also re-checks artifacts exist).
    assert schemas.hash_task_dir(task_dir).startswith("sha256:")
    # The rubric's variant matches the task's.
    assert rubric.variant == task.variant
    # Messy rubric weights sum to 1.0 (clean rubrics sum below it by design).
    if task.variant == "messy":
        assert abs(sum(c.weight for c in rubric.criteria) - 1.0) < 1e-6


# --------------------------------------------------------------------------- #
# Twin-pair invariants (MVP mess-penalty design)
# --------------------------------------------------------------------------- #
def _load_pair(clean_dir: Path):
    clean_task = schemas.load_task(clean_dir / "task.yaml")
    messy_dir = TASKS_DIR / clean_task.twin_of
    assert messy_dir.is_dir(), f"{clean_task.id}: twin_of '{clean_task.twin_of}' has no task dir"
    return clean_task, schemas.load_task(messy_dir / "task.yaml"), messy_dir


CLEAN_DIRS = [p for p in TASK_DIRS if schemas.load_task(p / "task.yaml").variant == "clean"]


def test_every_clean_task_declares_a_twin():
    for clean_dir in CLEAN_DIRS:
        assert schemas.load_task(clean_dir / "task.yaml").twin_of, clean_dir.name


@pytest.mark.parametrize("clean_dir", CLEAN_DIRS, ids=[p.name for p in CLEAN_DIRS])
def test_twin_pair_invariants(clean_dir: Path):
    clean_task, messy_task, messy_dir = _load_pair(clean_dir)

    # The pair shares category and — by design — a byte-identical prompt, so the
    # ONLY difference a model experiences is the artifacts (the noise).
    assert messy_task.variant == "messy"
    assert clean_task.category == messy_task.category
    assert clean_task.prompt == messy_task.prompt, (
        f"{clean_task.id}: prompt differs from its messy twin — twins must be a "
        "controlled comparison where only the artifacts change"
    )

    clean_rubric = schemas.load_rubric(clean_dir / "rubric.yaml")
    messy_rubric = schemas.load_rubric(messy_dir / "rubric.yaml")
    core_messy = {c.name: c for c in messy_rubric.criteria if c.kind == "core"}
    mess_messy = [c for c in messy_rubric.criteria if c.kind == "mess"]

    # The messy rubric must actually test mess handling.
    assert mess_messy, f"{messy_task.id}: messy rubric has no mess criteria"
    # CORE criteria are shared: same names, IDENTICAL weights (the mess-penalty
    # contract — mean core-criteria score difference is only meaningful if the
    # core set and weights match exactly).
    assert {c.name for c in clean_rubric.criteria} == set(core_messy), (
        f"{clean_task.id}: clean rubric criteria != messy twin's core criteria"
    )
    for c in clean_rubric.criteria:
        assert c.kind == "core"
        assert c.weight == core_messy[c.name].weight, (
            f"{clean_task.id}/{c.name}: weight {c.weight} != messy twin's "
            f"{core_messy[c.name].weight} — core weights must be identical"
        )
