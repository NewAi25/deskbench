"""DeskBench command-line interface (Typer).

Grows one command per box. Step 2 ships ``ping``/``models``; Step 4 adds
``run`` (tasks → raw results); Step 5 adds ``grade`` (raw results → scores);
Step 8 adds ``analyze`` (scores + human grades → summary + tables). ``render``
lands in Step 9.
"""

from __future__ import annotations

from pathlib import Path

import typer

from .analyzer import (
    DEFAULT_HUMAN_DIR,
    DEFAULT_SUMMARY,
    DEFAULT_TABLES_DIR,
    AnalyzerError,
    analyze,
    write_outputs,
)
from .analyzer import (
    DEFAULT_RAW_DIR as ANALYZER_RAW_DIR,
)
from .grader import DEFAULT_SCORES_DIR, GraderError, grade_raw_result
from .registry import DEFAULT_CONFIG, ConfigError, load_registry
from .runner import DEFAULT_RAW_DIR, RunnerError, resolve_task_dirs, run_task
from .schemas import RawResult
from .visualize import DEFAULT_SITE

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


@app.command()
def grade(
    task: str = typer.Option("all", help="Task id or 'all'."),
    model: str = typer.Option("all", help="Model id or 'all'."),
    config: Path = typer.Option(DEFAULT_CONFIG, help="Path to models.yaml"),
    tasks_dir: Path = typer.Option(Path("tasks"), help="Directory of task folders."),
    raw_dir: Path = typer.Option(DEFAULT_RAW_DIR, help="Where raw result JSONs live."),
    out: Path = typer.Option(DEFAULT_SCORES_DIR, help="Where to write score JSONs."),
):
    """Grade raw results with the held-out judge, writing one score JSON per result.

    Needs a judge key. Errored raw results (no answer) are skipped. A judge reply
    that won't parse after retries is reported and that result is left ungraded.
    """
    try:
        reg = load_registry(config)
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    out.mkdir(parents=True, exist_ok=True)
    graded = skipped = failed = 0
    for path in sorted(raw_dir.glob("*.json")):
        raw = RawResult.model_validate_json(path.read_text(encoding="utf-8"))
        if task != "all" and raw.task_id != task:
            continue
        if model != "all" and raw.model_id != model:
            continue
        if raw.error:
            skipped += 1
            typer.secho(
                f"[skip] {raw.record_id}: errored run ({raw.error})", fg=typer.colors.YELLOW
            )
            continue
        try:
            score = grade_raw_result(reg, raw, tasks_dir / raw.task_id)
        except GraderError as exc:
            failed += 1
            typer.secho(f"[FAIL] {raw.record_id}: {exc}", fg=typer.colors.RED)
            continue
        (out / f"{score.record_id}.json").write_text(
            score.model_dump_json(indent=2), encoding="utf-8"
        )
        graded += 1
        flag = "  AUTO-FAIL" if score.auto_fail_triggered else ""
        typer.secho(
            f"[ok]   {score.record_id}: {score.weighted_total:.2f}/5{flag}",
            fg=typer.colors.GREEN,
        )
    typer.echo(f"\nGraded {graded}, skipped {skipped} (errored), failed {failed} → {out}/")
    if failed:
        raise typer.Exit(1)


@app.command("analyze")
def analyze_cmd(
    tasks_dir: Path = typer.Option(Path("tasks"), help="Directory of task folders."),
    raw_dir: Path = typer.Option(ANALYZER_RAW_DIR, help="Raw result JSONs."),
    scores_dir: Path = typer.Option(DEFAULT_SCORES_DIR, help="Judge score JSONs."),
    human_dir: Path = typer.Option(DEFAULT_HUMAN_DIR, help="Human grade JSONs."),
    summary: Path = typer.Option(DEFAULT_SUMMARY, help="Where to write summary.json."),
    tables: Path = typer.Option(DEFAULT_TABLES_DIR, help="Where to write CSV tables."),
):
    """Aggregate scores + human grades into summary.json and CSV tables.

    Needs no keys and no network: it only reads the evidence already on disk.
    """
    try:
        result = analyze(tasks_dir, raw_dir, scores_dir, human_dir)
    except AnalyzerError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    written = write_outputs(result, summary, tables)

    m = result["matrix"]
    typer.echo(
        f"evidence: {m['n_raw']} raw / {m['n_judge_scores']} judge / {m['n_human_grades']} human"
    )
    typer.echo("leaderboard (judge overall | human overall):")
    for row in result["leaderboard"]:
        typer.echo(
            f"  {row['model']:22s} {row['judge']['mean_overall']:5.2f} | "
            f"{row['human']['mean_overall']:5.2f}"
        )
    a = result["agreement"]
    typer.echo(
        f"agreement: weighted-total r={a['weighted_total_pearson_r']} "
        f"MAE={a['weighted_total_mae']} auto-fail match={a['auto_fail_exact_match_rate']} "
        f"(n={a['n_paired']})"
    )
    for p in written:
        typer.echo(f"wrote {p}")


@app.command("render")
def render_cmd(
    tasks_dir: Path = typer.Option(Path("tasks"), help="Directory of task folders."),
    raw_dir: Path = typer.Option(ANALYZER_RAW_DIR, help="Raw result JSONs."),
    scores_dir: Path = typer.Option(DEFAULT_SCORES_DIR, help="Judge score JSONs."),
    human_dir: Path = typer.Option(DEFAULT_HUMAN_DIR, help="Human grade JSONs."),
    summary: Path = typer.Option(DEFAULT_SUMMARY, help="summary.json from `analyze`."),
    out: Path = typer.Option(DEFAULT_SITE, help="Output HTML path."),
):
    """Render the self-contained pilot dashboard (site/index.html).

    Needs no keys and no network: it inlines summary.json + the per-record
    evidence into one HTML file.
    """
    from .visualize import VisualizeError
    from .visualize import render as render_site

    try:
        path = render_site(tasks_dir, raw_dir, scores_dir, human_dir, summary, out)
    except VisualizeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    size_kb = path.stat().st_size / 1024
    typer.echo(f"wrote {path} ({size_kb:.0f} KB, self-contained)")


if __name__ == "__main__":
    app()
