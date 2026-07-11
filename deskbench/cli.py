"""DeskBench command-line interface (Typer).

Grows one command per box. Step 2 ships ``ping``/``models``; Step 4 adds
``run`` (execute tasks → raw results). Grade/analyze/render land in later steps.
"""

from __future__ import annotations

from pathlib import Path

import typer

from .registry import DEFAULT_CONFIG, ConfigError, load_registry
from .runner import DEFAULT_RAW_DIR, RunnerError, resolve_task_dirs, run_task

app = typer.Typer(
    help="DeskBench — a benchmark for messy real-world office work.",
    no_args_is_help=True,
)

# A tiny, deterministic prompt: cheap and unambiguous to eyeball.
_PING_PROMPT = "Reply with exactly the two words: hello there"


@app.command()
def models(config: Path = typer.Option(DEFAULT_CONFIG, help="Path to models.yaml")):
    """List the configured models and the judge."""
    try:
        reg = load_registry(config)
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    typer.echo("Leaderboard models:")
    for mid in reg.leaderboard_ids:
        cfg = reg.get(mid)
        typer.echo(f"  - {mid:22s} {cfg.litellm_model}  (key: {cfg.api_key_env})")
    judge = reg.get(reg.judge_id)
    typer.echo(f"Judge (held out): {judge.id}  {judge.litellm_model}  (key: {judge.api_key_env})")


@app.command()
def ping(
    config: Path = typer.Option(DEFAULT_CONFIG, help="Path to models.yaml"),
    include_judge: bool = typer.Option(True, help="Also ping the judge model."),
):
    """Send one tiny prompt to every provider and report ok/latency or the error.

    Needs real keys in your environment (.env). Cache is bypassed so this always
    makes a live call. Exits non-zero if any model fails, so it doubles as a
    smoke test.
    """
    try:
        reg = load_registry(config)
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    ids = reg.all_ids() if include_judge else reg.leaderboard_ids
    failures = 0
    for mid in ids:
        try:
            comp = reg.complete(mid, _PING_PROMPT, task_hash="ping", run_index=0, use_cache=False)
            preview = comp.text.strip().replace("\n", " ")[:60]
            typer.secho(
                f"[ok]   {mid:22s} {comp.latency_s:5.2f}s  {comp.tokens_out:>4} tok  {preview!r}",
                fg=typer.colors.GREEN,
            )
        except Exception as exc:  # noqa: BLE001 — surface any provider error verbatim
            failures += 1
            typer.secho(f"[FAIL] {mid:22s} {type(exc).__name__}: {exc}", fg=typer.colors.RED)

    if failures:
        typer.secho(f"\n{failures} model(s) failed to respond.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    typer.secho(f"\nAll {len(ids)} model(s) responded.", fg=typer.colors.GREEN)


@app.command()
def run(
    task: str = typer.Option("all", help="Task id (e.g. T01-inbox-triage) or 'all'."),
    model: str = typer.Option("all", help="Model id or 'all' (all leaderboard models)."),
    n: int = typer.Option(3, "-n", "--runs", help="Runs per (task, model)."),
    config: Path = typer.Option(DEFAULT_CONFIG, help="Path to models.yaml"),
    tasks_dir: Path = typer.Option(Path("tasks"), help="Directory of task folders."),
    out: Path = typer.Option(DEFAULT_RAW_DIR, help="Where to write raw result JSONs."),
    no_resume: bool = typer.Option(False, help="Re-run even completed runs."),
):
    """Execute tasks against models, writing one raw result JSON per run.

    Needs real keys. Resumable: existing successful runs are skipped unless
    --no-resume. Errors are recorded as results, not raised.
    """
    try:
        reg = load_registry(config)
        task_dirs = resolve_task_dirs(task, tasks_dir)
    except (ConfigError, RunnerError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    model_ids = reg.leaderboard_ids if model == "all" else [model]
    total_err = 0
    for task_dir in task_dirs:
        for model_id in model_ids:
            try:
                results = run_task(reg, task_dir, model_id, n, out_dir=out, resume=not no_resume)
            except (ConfigError, RunnerError) as exc:
                typer.secho(f"[skip] {task_dir.name} × {model_id}: {exc}", fg=typer.colors.YELLOW)
                continue
            errs = sum(1 for r in results if r.error)
            total_err += errs
            colour = typer.colors.RED if errs else typer.colors.GREEN
            typer.secho(
                f"[{task_dir.name} × {model_id}] {len(results)} run(s), {errs} error(s)",
                fg=colour,
            )
    typer.echo(f"\nWrote raw results to {out}/ ({total_err} errored run(s)).")
    if total_err:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
