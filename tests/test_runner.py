"""Tests for the runner (Box 3). All model calls are mocked — no keys, no network.

Covers: N raw JSONs written and valid; errors captured as results (not raised);
resumability (completed runs skipped, errored runs retried); tool-task rejection;
task-selector resolution; and validation of the committed raw-result fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from deskbench.registry import Registry, load_registry
from deskbench.runner import (
    RunnerError,
    build_prompt,
    resolve_task_dirs,
    run_task,
)
from deskbench.schemas import RawResult, load_task

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "config" / "models.yaml"
T01 = REPO_ROOT / "tasks" / "T01-inbox-triage"
FIXTURES = REPO_ROOT / "tests" / "fixtures"


def _registry(tmp_path) -> Registry:
    return load_registry(CONFIG, cache_dir=tmp_path / "cache", retry_wait_min=0, retry_wait_max=0)


def _mock_ok(monkeypatch, text="MODEL ANSWER"):
    calls = {"n": 0}

    def fake(self, cfg, prompt, sampling):
        calls["n"] += 1
        return (f"{text} #{calls['n']}", 11, 7)

    monkeypatch.setattr(Registry, "_raw_completion", fake)
    return calls


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_run_task_writes_n_valid_results(tmp_path, monkeypatch):
    _mock_ok(monkeypatch)
    reg = _registry(tmp_path)
    out = tmp_path / "raw"
    results = run_task(reg, T01, "gemini-flash", 3, out_dir=out)

    assert len(results) == 3
    files = sorted(out.glob("*.json"))
    assert len(files) == 3
    for path in files:
        rr = RawResult.model_validate_json(path.read_text(encoding="utf-8"))
        assert rr.task_id == "T01-inbox-triage"
        assert rr.model_id == "gemini-flash"
        assert rr.error is None
        assert rr.output.startswith("MODEL ANSWER")
        assert rr.task_hash.startswith("sha256:")
        assert rr.cost_usd == 0.0
    # Filenames are content-addressed and distinct per run.
    assert {p.stem for p in files} == {f"T01-inbox-triage__gemini-flash__run{i}" for i in range(3)}


def test_run_records_vendor_default_sampling(tmp_path, monkeypatch):
    _mock_ok(monkeypatch)
    reg = _registry(tmp_path)
    results = run_task(reg, T01, "gemini-flash", 1, out_dir=tmp_path / "raw")
    assert results[0].sampling.source == "vendor-default"


# --------------------------------------------------------------------------- #
# Errors are results, not crashes
# --------------------------------------------------------------------------- #
def test_provider_error_is_captured_as_result(tmp_path, monkeypatch):
    def boom(self, cfg, prompt, sampling):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(Registry, "_raw_completion", boom)
    reg = _registry(tmp_path)
    out = tmp_path / "raw"
    results = run_task(reg, T01, "gemini-flash", 2, out_dir=out)

    assert len(results) == 2
    for rr in results:
        assert rr.error is not None
        assert "provider exploded" in rr.error
        assert rr.output == ""
    # The errored results were still written to disk.
    assert len(list(out.glob("*.json"))) == 2


# --------------------------------------------------------------------------- #
# Resumability
# --------------------------------------------------------------------------- #
def test_resume_skips_completed_runs(tmp_path, monkeypatch):
    calls = _mock_ok(monkeypatch)
    reg = _registry(tmp_path)
    out = tmp_path / "raw"
    run_task(reg, T01, "gemini-flash", 3, out_dir=out)
    assert calls["n"] == 3
    # Second sweep: everything already succeeded, so no new provider calls.
    run_task(reg, T01, "gemini-flash", 3, out_dir=out)
    assert calls["n"] == 3


def test_resume_retries_errored_runs(tmp_path, monkeypatch):
    # First sweep: all error.
    def boom(self, cfg, prompt, sampling):
        raise RuntimeError("down")

    monkeypatch.setattr(Registry, "_raw_completion", boom)
    reg = _registry(tmp_path)
    out = tmp_path / "raw"
    run_task(reg, T01, "gemini-flash", 2, out_dir=out)

    # Now the provider recovers; resume should retry the errored runs.
    calls = _mock_ok(monkeypatch)
    results = run_task(reg, T01, "gemini-flash", 2, out_dir=out)
    assert calls["n"] == 2  # both errored runs were retried
    assert all(r.error is None for r in results)


def test_no_resume_reruns_everything(tmp_path, monkeypatch):
    calls = _mock_ok(monkeypatch)
    reg = _registry(tmp_path)
    out = tmp_path / "raw"
    run_task(reg, T01, "gemini-flash", 2, out_dir=out)
    run_task(reg, T01, "gemini-flash", 2, out_dir=out, resume=False, use_cache=False)
    assert calls["n"] == 4


# --------------------------------------------------------------------------- #
# Tool containment & selectors
# --------------------------------------------------------------------------- #
def test_tool_task_is_rejected(tmp_path, monkeypatch):
    _mock_ok(monkeypatch)
    reg = _registry(tmp_path)
    # Clone T01 and give it a tool requirement.
    tool_task = tmp_path / "T99-tool"
    (tool_task / "artifacts").mkdir(parents=True)
    data = yaml.safe_load((T01 / "task.yaml").read_text(encoding="utf-8"))
    data["id"] = "T99-tool"
    data["tools_allowed"] = ["python"]
    data["artifacts"] = []
    (tool_task / "task.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(RunnerError) as exc:
        run_task(reg, tool_task, "gemini-flash", 1, out_dir=tmp_path / "raw")
    assert "self-contained" in str(exc.value)


def test_n_runs_must_be_positive(tmp_path, monkeypatch):
    _mock_ok(monkeypatch)
    reg = _registry(tmp_path)
    with pytest.raises(RunnerError):
        run_task(reg, T01, "gemini-flash", 0, out_dir=tmp_path / "raw")


def test_resolve_task_dirs():
    all_dirs = resolve_task_dirs("all", REPO_ROOT / "tasks")
    names = {p.name for p in all_dirs}
    assert {"T01-inbox-triage", "T02-spreadsheet-reconciliation"}.issubset(names)
    one = resolve_task_dirs("T01-inbox-triage", REPO_ROOT / "tasks")
    assert [p.name for p in one] == ["T01-inbox-triage"]
    with pytest.raises(RunnerError):
        resolve_task_dirs("T404-nope", REPO_ROOT / "tasks")


def test_build_prompt_inlines_all_artifacts():
    task = load_task(T01 / "task.yaml")
    prompt = build_prompt(task, T01)
    assert "inbox.md" in prompt and "calendar.md" in prompt
    assert "Board deck" in prompt  # from inbox.md
    assert "Board prep with CFO" in prompt  # from calendar.md


# --------------------------------------------------------------------------- #
# Committed fixture
# --------------------------------------------------------------------------- #
def test_raw_result_fixture_validates():
    fixture = FIXTURES / "sample_raw_result.json"
    rr = RawResult.model_validate_json(fixture.read_text(encoding="utf-8"))
    assert rr.task_id == "T01-inbox-triage"
    assert rr.task_hash.startswith("sha256:")
