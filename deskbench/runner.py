"""Runner (Box 3): task × model × N runs -> one RawResult JSON per run on disk.

For each run it inlines the task's artifacts into a single self-contained prompt,
asks the model (through the cached, retried registry), and writes a validated
`RawResult` to `results/raw/{task}__{model}__run{n}.json`.

Design commitments:

* **Errors are results, not crashes.** A provider failure is captured as a
  RawResult with `error` set and empty `output`, so one bad call never aborts a
  sweep and failures show up honestly in the analysis.
* **Resumable after an interrupt.** A run whose JSON already exists *and
  succeeded* is loaded from disk and skipped; an interrupted sweep re-runs only
  what's missing or errored. Combined with the registry's per-run cache, reruns
  cost zero calls.
* **Tool use is contained.** Only two of the twelve v1 tasks will use tools; the
  pilots are self-contained. Until the first tool task lands, a task that
  declares `tools_allowed` is rejected with a clear message rather than run
  through an unimplemented agent loop.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .registry import Registry
from .schemas import (
    RawResult,
    SamplingParams,
    Task,
    hash_task_dir,
    load_task,
    record_id,
)

DEFAULT_RAW_DIR = Path("results/raw")


class RunnerError(RuntimeError):
    """Raised when a task cannot be executed by the v1 runner."""


def build_prompt(task: Task, task_dir: str | Path) -> str:
    """Inline a self-contained task's artifacts into one prompt string."""
    task_dir = Path(task_dir)
    parts = [task.prompt.strip(), "\n\n--- MATERIALS ---"]
    for name in task.artifacts:
        content = (task_dir / "artifacts" / name).read_text(encoding="utf-8")
        parts.append(f"\n\n### {name}\n{content.rstrip()}")
    return "".join(parts)


def _now() -> datetime:
    return datetime.now(UTC)


def run_once(
    registry: Registry,
    task: Task,
    task_dir: str | Path,
    model_id: str,
    run_index: int,
    *,
    task_hash: str,
    sampling: SamplingParams | None = None,
    use_cache: bool = True,
) -> RawResult:
    """Execute a single (task, model, run) and return a RawResult.

    Any exception from the provider is captured into the RawResult's `error`
    field rather than propagated.
    """
    effective_sampling = sampling or registry.get(model_id).sampling
    prompt = build_prompt(task, task_dir)
    try:
        comp = registry.complete(
            model_id,
            prompt,
            task_hash=task_hash,
            run_index=run_index,
            sampling=sampling,
            use_cache=use_cache,
        )
        return RawResult(
            task_id=task.id,
            model_id=model_id,
            run_index=run_index,
            variant=task.variant,
            output=comp.text,
            tokens_in=comp.tokens_in,
            tokens_out=comp.tokens_out,
            latency_s=comp.latency_s,
            cost_usd=0.0,
            timestamp=_now(),
            error=None,
            sampling=effective_sampling,
            task_hash=task_hash,
        )
    except Exception as exc:  # noqa: BLE001 — a failed call is a recorded result
        return RawResult(
            task_id=task.id,
            model_id=model_id,
            run_index=run_index,
            variant=task.variant,
            output="",
            tokens_in=0,
            tokens_out=0,
            latency_s=0.0,
            cost_usd=0.0,
            timestamp=_now(),
            error=f"{type(exc).__name__}: {exc}",
            sampling=effective_sampling,
            task_hash=task_hash,
        )


def run_task(
    registry: Registry,
    task_dir: str | Path,
    model_id: str,
    n_runs: int,
    *,
    out_dir: str | Path = DEFAULT_RAW_DIR,
    sampling: SamplingParams | None = None,
    resume: bool = True,
    use_cache: bool = True,
) -> list[RawResult]:
    """Run one task against one model N times, writing a JSON per run.

    Returns the list of RawResults (loaded from disk where already present).
    """
    task_dir = Path(task_dir)
    task = load_task(task_dir / "task.yaml")
    if task.tools_allowed:
        raise RunnerError(
            f"task {task.id} declares tools_allowed={task.tools_allowed}; the v1 "
            "runner only executes self-contained tasks. Tool-using execution "
            "arrives with the first tool task (BUILD_PLAN §5, Step 4)."
        )
    if n_runs < 1:
        raise RunnerError(f"n_runs must be >= 1, got {n_runs}")

    task_hash = hash_task_dir(task_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[RawResult] = []
    for run_index in range(n_runs):
        path = out_dir / f"{record_id(task.id, model_id, run_index)}.json"
        if resume and path.exists():
            existing = RawResult.model_validate_json(path.read_text(encoding="utf-8"))
            if existing.error is None:
                results.append(existing)
                continue  # completed run — don't re-bill it
            # else: a prior errored run — fall through and retry it
        result = run_once(
            registry,
            task,
            task_dir,
            model_id,
            run_index,
            task_hash=task_hash,
            sampling=sampling,
            use_cache=use_cache,
        )
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        results.append(result)
    return results


def resolve_task_dirs(task: str, tasks_dir: str | Path = "tasks") -> list[Path]:
    """Resolve a task selector ('all' or a task id) to task directories."""
    tasks_dir = Path(tasks_dir)
    if task == "all":
        return sorted(p for p in tasks_dir.iterdir() if p.is_dir() and (p / "task.yaml").exists())
    candidate = tasks_dir / task
    if not (candidate / "task.yaml").exists():
        raise RunnerError(f"no task '{task}' under {tasks_dir}/")
    return [candidate]
