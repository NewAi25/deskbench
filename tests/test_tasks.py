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
    assert {"T01-inbox-triage", "T02-spreadsheet-reconciliation"}.issubset(ids)


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
    # Weights sum to 1.0 is enforced by the schema, but assert once more here.
    assert abs(sum(c.weight for c in rubric.criteria) - 1.0) < 1e-6
