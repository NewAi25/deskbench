"""Model registry (Box 2): every model is a config entry, never code.

Loads ``config/models.yaml`` into validated :class:`ModelConfig` objects, wraps
provider calls (via LiteLLM) in tenacity retry/backoff for free-tier rate
limits, and caches responses on disk so reruns cost zero calls.

Two ARCHITECTURE_REVIEW fixes live here:

* **Fix #1 — judge independence.** The judge is a separate ``judge:`` entry, and
  the registry refuses to load a config whose judge id or model string collides
  with any leaderboard model. The judge can never grade its own family.

* **Fix #4 — cache key includes run_index.** The cache is keyed on
  ``(model_id, task_hash, sampling_params, run_index)``. Keying only on
  (model, prompt) would make runs 2..N return run 1's cached answer and collapse
  all run-to-run variance to zero — the pipeline would *appear* to work while
  quietly falsifying a headline metric. ``test_registry`` proves two runs of the
  same task/model get distinct keys and therefore CAN differ.

LiteLLM is imported lazily inside :meth:`Registry._raw_completion` so the
registry (and its tests) import with no provider SDKs and no network.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from .schemas import SamplingParams

DEFAULT_CONFIG = Path("config/models.yaml")
DEFAULT_CACHE_DIR = Path(".cache")

# Exception *class names* treated as transient and worth retrying. Matched by
# name so we need not import LiteLLM's exception hierarchy at module load.
_TRANSIENT_NAMES = frozenset(
    {
        "RateLimitError",
        "APIConnectionError",
        "APIConnectionErrorType",
        "Timeout",
        "APITimeoutError",
        "InternalServerError",
        "ServiceUnavailableError",
        "APIError",
        "APIStatusError",
    }
)


def _is_transient(exc: BaseException) -> bool:
    return type(exc).__name__ in _TRANSIENT_NAMES


class ConfigError(ValueError):
    """Raised when models.yaml is missing, malformed, or violates a policy."""


# --------------------------------------------------------------------------- #
# Config model
# --------------------------------------------------------------------------- #
class ModelConfig(BaseModel):
    """One registry entry: a model reduced to pure configuration."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    provider: str = Field(..., min_length=1)
    #: The exact string passed to ``litellm.completion(model=...)``.
    litellm_model: str = Field(..., min_length=1)
    #: Name of the env var holding the API key (never the key itself).
    api_key_env: str = Field(..., min_length=1)
    #: Optional base URL for OpenAI-compatible providers (e.g. Z.ai).
    base_url: str | None = None
    sampling: SamplingParams = Field(default_factory=SamplingParams)
    #: Free-form note (e.g. why a judge was chosen).
    note: str | None = None
    role: str = "leaderboard"


# --------------------------------------------------------------------------- #
# Response cache (fix #4)
# --------------------------------------------------------------------------- #
class ResponseCache:
    """On-disk response cache keyed on (model_id, task_hash, sampling, run_index).

    Including ``run_index`` in the key is the whole point: it lets repeated runs
    of the same task/model be independent calls (so variance is real) while still
    letting an *interrupted* run resume without re-billing completed runs.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def key(
        self,
        model_id: str,
        task_hash: str,
        sampling: SamplingParams,
        run_index: int,
    ) -> str:
        payload = {
            "model_id": model_id,
            "task_hash": task_hash,
            "sampling": sampling.model_dump(mode="json"),
            "run_index": run_index,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:32]

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def set(self, key: str, value: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._path(key).write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )


# --------------------------------------------------------------------------- #
# Completion result
# --------------------------------------------------------------------------- #
@dataclass
class Completion:
    """A single model response (the runner wraps this into a RawResult)."""

    text: str
    tokens_in: int
    tokens_out: int
    latency_s: float
    model_id: str
    cached: bool = False


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
class Registry:
    """Holds validated model configs and executes cached, retried completions."""

    def __init__(
        self,
        models: list[ModelConfig],
        judge: ModelConfig,
        *,
        cache_dir: str | Path = DEFAULT_CACHE_DIR,
        retry_attempts: int = 5,
        retry_wait_min: float = 1.0,
        retry_wait_max: float = 30.0,
    ):
        self._by_id: dict[str, ModelConfig] = {}
        self.leaderboard_ids: list[str] = []
        for m in models:
            self._register(m)
            self.leaderboard_ids.append(m.id)
        judge = judge.model_copy(update={"role": "judge"})
        self.judge_id = judge.id
        # Independence is checked BEFORE registering the judge, so a judge that
        # collides with a leaderboard model reports the specific policy violation
        # rather than a generic duplicate-id error.
        self._validate_independence(judge)
        self._register(judge)

        self.cache = ResponseCache(cache_dir)
        self._retry_attempts = retry_attempts
        self._retry_wait_min = retry_wait_min
        self._retry_wait_max = retry_wait_max

    # -- construction helpers ------------------------------------------------
    def _register(self, cfg: ModelConfig) -> None:
        if cfg.id in self._by_id:
            raise ConfigError(f"duplicate model id: {cfg.id!r}")
        self._by_id[cfg.id] = cfg

    def _validate_independence(self, judge: ModelConfig) -> None:
        if len(self.leaderboard_ids) < 4:
            raise ConfigError(
                f"need at least 4 leaderboard models, got {len(self.leaderboard_ids)}"
            )
        if self.judge_id in self.leaderboard_ids:
            raise ConfigError(
                f"judge id {self.judge_id!r} must not be a leaderboard model (fix #1)"
            )
        leaderboard_models = {self._by_id[i].litellm_model for i in self.leaderboard_ids}
        if judge.litellm_model in leaderboard_models:
            raise ConfigError(
                f"judge model {judge.litellm_model!r} is also a leaderboard model; "
                "the judge must be independent (fix #1)"
            )

    # -- accessors -----------------------------------------------------------
    def get(self, model_id: str) -> ModelConfig:
        try:
            return self._by_id[model_id]
        except KeyError:
            raise ConfigError(f"unknown model id: {model_id!r}") from None

    def all_ids(self) -> list[str]:
        return [*self.leaderboard_ids, self.judge_id]

    # -- execution -----------------------------------------------------------
    def _retryer(self) -> Retrying:
        return Retrying(
            stop=stop_after_attempt(self._retry_attempts),
            wait=wait_exponential(multiplier=1, min=self._retry_wait_min, max=self._retry_wait_max),
            retry=retry_if_exception(_is_transient),
            reraise=True,
        )

    def _raw_completion(
        self, cfg: ModelConfig, prompt: str, sampling: SamplingParams
    ) -> tuple[str, int, int]:
        """Do the actual provider call. Isolated so tests can monkeypatch it."""
        api_key = os.environ.get(cfg.api_key_env)
        if not api_key:
            raise ConfigError(f"env var {cfg.api_key_env} is not set (needed for model {cfg.id})")

        import litellm  # lazy: keeps the module importable with no provider SDKs

        kwargs: dict[str, Any] = {
            "model": cfg.litellm_model,
            "messages": [{"role": "user", "content": prompt}],
            "api_key": api_key,
        }
        if cfg.base_url:
            kwargs["api_base"] = cfg.base_url
        # Only send sampling params that are explicitly set; otherwise let the
        # provider apply its own defaults (vendor-default policy, fix #3).
        if sampling.source == "explicit":
            for name in ("temperature", "top_p", "max_tokens", "seed"):
                value = getattr(sampling, name)
                if value is not None:
                    kwargs[name] = value

        response = litellm.completion(**kwargs)
        text = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
        return text, tokens_in, tokens_out

    def complete(
        self,
        model_id: str,
        prompt: str,
        *,
        task_hash: str,
        run_index: int = 0,
        sampling: SamplingParams | None = None,
        use_cache: bool = True,
    ) -> Completion:
        """Return a completion, from cache if present, else a live retried call."""
        cfg = self.get(model_id)
        sp = sampling or cfg.sampling
        key = self.cache.key(model_id, task_hash, sp, run_index)

        if use_cache:
            hit = self.cache.get(key)
            if hit is not None:
                return Completion(**hit, cached=True)

        start = time.perf_counter()
        text, tokens_in, tokens_out = self._retryer()(self._raw_completion, cfg, prompt, sp)
        latency_s = time.perf_counter() - start

        payload = {
            "text": text,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_s": latency_s,
            "model_id": model_id,
        }
        if use_cache:
            self.cache.set(key, payload)
        return Completion(**payload)


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def load_registry(
    path: str | Path = DEFAULT_CONFIG,
    *,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    retry_attempts: int = 5,
    retry_wait_min: float = 1.0,
    retry_wait_max: float = 30.0,
) -> Registry:
    """Load and validate ``models.yaml`` into a :class:`Registry`."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"{path}: model registry not found")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a YAML mapping at the top level")

    raw_models = data.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise ConfigError(f"{path}: 'models' must be a non-empty list")
    raw_judge = data.get("judge")
    if not isinstance(raw_judge, dict):
        raise ConfigError(f"{path}: a 'judge' entry is required (fix #1 judge independence)")

    try:
        models = [ModelConfig.model_validate(m) for m in raw_models]
        judge = ModelConfig.model_validate(raw_judge)
    except Exception as exc:  # pydantic ValidationError -> readable ConfigError
        raise ConfigError(f"{path}: invalid model entry:\n{exc}") from exc

    return Registry(
        models,
        judge,
        cache_dir=cache_dir,
        retry_attempts=retry_attempts,
        retry_wait_min=retry_wait_min,
        retry_wait_max=retry_wait_max,
    )
