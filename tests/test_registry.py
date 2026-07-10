"""Tests for the model registry: loading/validation, cache keying, retry.

All provider calls are mocked — CI has no API keys and makes no network calls.
The headline test is ``test_two_runs_of_same_task_can_differ`` (fix #4): the
cache key must include run_index so run-to-run variance cannot silently collapse.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from deskbench.registry import (
    Completion,
    ConfigError,
    ModelConfig,
    Registry,
    ResponseCache,
    _is_transient,
    load_registry,
)
from deskbench.schemas import SamplingParams

CONFIG = Path(__file__).resolve().parents[1] / "config" / "models.yaml"


def _fast_registry(tmp_path, **kw) -> Registry:
    """The real config, but with a temp cache and zero retry backoff."""
    return load_registry(
        CONFIG,
        cache_dir=tmp_path,
        retry_attempts=kw.pop("retry_attempts", 5),
        retry_wait_min=0.0,
        retry_wait_max=0.0,
    )


# --------------------------------------------------------------------------- #
# Loading & validation
# --------------------------------------------------------------------------- #
def test_loads_four_leaderboard_and_a_judge(tmp_path):
    reg = _fast_registry(tmp_path)
    assert len(reg.leaderboard_ids) >= 4
    assert reg.judge_id
    assert reg.judge_id not in reg.leaderboard_ids
    # Judge model string is independent of every leaderboard model (fix #1).
    judge_model = reg.get(reg.judge_id).litellm_model
    board_models = {reg.get(i).litellm_model for i in reg.leaderboard_ids}
    assert judge_model not in board_models


def test_every_entry_reads_key_from_env_not_file(tmp_path):
    reg = _fast_registry(tmp_path)
    for mid in reg.all_ids():
        cfg = reg.get(mid)
        assert cfg.api_key_env.isupper()  # an env var name, never a literal key
        assert cfg.api_key_env.endswith("_API_KEY")


def _write_config(tmp_path, models, judge) -> Path:
    p = tmp_path / "models.yaml"
    p.write_text(yaml.safe_dump({"models": models, "judge": judge}), encoding="utf-8")
    return p


def _model(mid, litellm_model="prov/model-x"):
    return {
        "id": mid,
        "provider": "p",
        "litellm_model": litellm_model,
        "api_key_env": "X_API_KEY",
    }


def test_judge_sharing_leaderboard_id_is_rejected(tmp_path):
    models = [_model(f"m{i}") for i in range(4)]
    judge = _model("m0")  # collides with a leaderboard id
    cfg = _write_config(tmp_path, models, judge)
    with pytest.raises(ConfigError) as exc:
        load_registry(cfg, cache_dir=tmp_path)
    assert "must not be a leaderboard model" in str(exc.value)


def test_judge_sharing_leaderboard_model_string_is_rejected(tmp_path):
    models = [_model(f"m{i}", litellm_model=f"prov/model-{i}") for i in range(4)]
    judge = _model("judge", litellm_model="prov/model-0")  # same model as m0
    cfg = _write_config(tmp_path, models, judge)
    with pytest.raises(ConfigError) as exc:
        load_registry(cfg, cache_dir=tmp_path)
    assert "must be independent" in str(exc.value)


def test_fewer_than_four_models_is_rejected(tmp_path):
    models = [_model(f"m{i}") for i in range(3)]
    judge = _model("judge")
    cfg = _write_config(tmp_path, models, judge)
    with pytest.raises(ConfigError) as exc:
        load_registry(cfg, cache_dir=tmp_path)
    assert "at least 4" in str(exc.value)


def test_missing_judge_is_rejected(tmp_path):
    p = tmp_path / "models.yaml"
    p.write_text(yaml.safe_dump({"models": [_model(f"m{i}") for i in range(4)]}), encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_registry(p, cache_dir=tmp_path)
    assert "judge" in str(exc.value)


def test_unknown_field_in_entry_is_rejected(tmp_path):
    models = [_model(f"m{i}") for i in range(4)]
    models[0]["typo_field"] = 1
    judge = _model("judge")
    cfg = _write_config(tmp_path, models, judge)
    with pytest.raises(ConfigError):
        load_registry(cfg, cache_dir=tmp_path)


# --------------------------------------------------------------------------- #
# Cache keying (fix #4)
# --------------------------------------------------------------------------- #
def test_cache_key_includes_run_index(tmp_path):
    cache = ResponseCache(tmp_path)
    sp = SamplingParams()
    k0 = cache.key("m", "task#abc", sp, 0)
    k1 = cache.key("m", "task#abc", sp, 1)
    assert k0 != k1, "runs 0 and 1 must have distinct cache keys (fix #4)"
    # Deterministic for identical inputs.
    assert k0 == cache.key("m", "task#abc", sp, 0)


def test_cache_key_varies_with_sampling(tmp_path):
    cache = ResponseCache(tmp_path)
    default = cache.key("m", "h", SamplingParams(), 0)
    explicit = cache.key("m", "h", SamplingParams(temperature=0.2, source="explicit"), 0)
    assert default != explicit


def test_cache_key_varies_with_task_hash(tmp_path):
    cache = ResponseCache(tmp_path)
    assert cache.key("m", "h1", SamplingParams(), 0) != cache.key("m", "h2", SamplingParams(), 0)


def test_cache_roundtrip(tmp_path):
    cache = ResponseCache(tmp_path)
    assert cache.get("nope") is None
    cache.set("k", {"text": "hi", "n": 1})
    assert cache.get("k") == {"text": "hi", "n": 1}


# --------------------------------------------------------------------------- #
# Execution: caching, run independence (fix #4), retry
# --------------------------------------------------------------------------- #
def test_two_runs_of_same_task_can_differ(tmp_path, monkeypatch):
    """Regression for fix #4: distinct run_index -> distinct call -> may differ."""
    reg = _fast_registry(tmp_path)
    calls = {"n": 0}

    def fake(self, cfg, prompt, sampling):
        calls["n"] += 1
        return (f"response-{calls['n']}", 5, 3)

    monkeypatch.setattr(Registry, "_raw_completion", fake)
    mid = reg.leaderboard_ids[0]

    r0 = reg.complete(mid, "p", task_hash="t", run_index=0)
    r1 = reg.complete(mid, "p", task_hash="t", run_index=1)
    assert r0.text != r1.text  # two live calls, not one cached answer reused

    # And caching still works: repeating run 0 serves from disk, no new call.
    n_before = calls["n"]
    r0_again = reg.complete(mid, "p", task_hash="t", run_index=0)
    assert calls["n"] == n_before
    assert r0_again.cached is True
    assert r0_again.text == r0.text


def test_cache_can_be_bypassed(tmp_path, monkeypatch):
    reg = _fast_registry(tmp_path)
    calls = {"n": 0}

    def fake(self, cfg, prompt, sampling):
        calls["n"] += 1
        return ("x", 1, 1)

    monkeypatch.setattr(Registry, "_raw_completion", fake)
    mid = reg.leaderboard_ids[0]
    reg.complete(mid, "p", task_hash="t", run_index=0, use_cache=False)
    reg.complete(mid, "p", task_hash="t", run_index=0, use_cache=False)
    assert calls["n"] == 2  # no caching when bypassed


def test_retry_then_success_on_transient(tmp_path, monkeypatch):
    reg = _fast_registry(tmp_path, retry_attempts=4)
    attempts = {"n": 0}

    class RateLimitError(Exception):
        pass

    def flaky(self, cfg, prompt, sampling):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RateLimitError("slow down")
        return ("recovered", 1, 1)

    monkeypatch.setattr(Registry, "_raw_completion", flaky)
    comp = reg.complete(reg.leaderboard_ids[0], "p", task_hash="t", use_cache=False)
    assert comp.text == "recovered"
    assert attempts["n"] == 3


def test_non_transient_error_is_not_retried(tmp_path, monkeypatch):
    reg = _fast_registry(tmp_path, retry_attempts=5)
    attempts = {"n": 0}

    def boom(self, cfg, prompt, sampling):
        attempts["n"] += 1
        raise ValueError("hard failure")

    monkeypatch.setattr(Registry, "_raw_completion", boom)
    with pytest.raises(ValueError):
        reg.complete(reg.leaderboard_ids[0], "p", task_hash="t", use_cache=False)
    assert attempts["n"] == 1  # tried once, not retried


def test_missing_key_raises_without_network(tmp_path, monkeypatch):
    # No monkeypatch of _raw_completion: it must fail on the missing key BEFORE
    # it ever imports litellm or touches the network.
    reg = _fast_registry(tmp_path)
    cfg = reg.get(reg.leaderboard_ids[0])
    monkeypatch.delenv(cfg.api_key_env, raising=False)
    with pytest.raises(ConfigError) as exc:
        reg.complete(reg.leaderboard_ids[0], "p", task_hash="t", use_cache=False)
    assert cfg.api_key_env in str(exc.value)


def test_unknown_model_id_raises(tmp_path):
    reg = _fast_registry(tmp_path)
    with pytest.raises(ConfigError):
        reg.get("does-not-exist")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def test_is_transient_matches_by_class_name():
    class RateLimitError(Exception):
        pass

    class ValueError2(Exception):
        pass

    assert _is_transient(RateLimitError())
    assert not _is_transient(ValueError("x"))


def test_completion_dataclass_defaults():
    c = Completion(text="t", tokens_in=1, tokens_out=2, latency_s=0.1, model_id="m")
    assert c.cached is False


def test_modelconfig_defaults_to_vendor_default_sampling():
    cfg = ModelConfig(id="m", provider="p", litellm_model="x/y", api_key_env="X_API_KEY")
    assert cfg.sampling.source == "vendor-default"
    assert cfg.role == "leaderboard"
