"""Typed data contracts for the DeskBench pipeline (Box connectors).

Every box in the pipeline communicates only through files on disk, and every one
of those files conforms to one of the four contracts defined here:

    Task        <- tasks/<id>/task.yaml
    Rubric      <- tasks/<id>/rubric.yaml
    RawResult   -> results/raw/<record>.json     (written by the runner)
    Score       -> results/scores/<record>.json  (written by the grader)

Two ARCHITECTURE_REVIEW fixes are baked in at the contract layer, where they are
cheap to build and impossible to retrofit honestly:

* **Fix #2 — content-hash versioning.** :func:`hash_task_dir` and
  :func:`hash_rubric` compute a stable hash over the *semantic* content of a task
  directory (prompt + artifact bytes + reference) and a rubric. Every RawResult
  embeds ``task_hash``; every Score embeds ``task_hash`` and ``rubric_hash``. The
  analyzer can then refuse to aggregate records whose hashes no longer match the
  current suite, so reruns never silently mix task versions.

* **Fix #3 — sampling policy on every result.** :class:`SamplingParams` records
  the temperature / top_p / max_tokens / seed used for a run (default: the
  provider's own defaults). "Variance under vendor-default settings" is then a
  claim the data can actually back, because the settings travel with the data.

Records are content-addressed by ``{task_id}__{model_id}__run{n}`` (see
:func:`record_id`) so reruns never clobber history.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

# The five task categories are fixed (PRD / BUILD_PLAN §4). Anything else is a
# typo in task.yaml and must fail validation.
Category = Literal[
    "communication",
    "data-wrangling",
    "synthesis",
    "planning",
    "compliance",
]
CATEGORIES: tuple[str, ...] = (
    "communication",
    "data-wrangling",
    "synthesis",
    "planning",
    "compliance",
)

Difficulty = Literal["easy", "medium", "hard"]

# Fixed failure-mode taxonomy (ARCHITECTURE_REVIEW fix #5; human-assigned in v1).
FailureMode = Literal[
    "hallucinated-data",
    "dropped-constraint",
    "false-confidence",
    "format-failure",
    "refusal",
    "error",
]

_HASH_PREFIX = "sha256"
_HASH_LEN = 12


class SchemaError(ValueError):
    """Raised when a YAML file on disk fails to validate against its contract.

    Wraps pydantic's ``ValidationError`` with the offending file path so the
    message points a task author straight at the file to fix.
    """


# --------------------------------------------------------------------------- #
# Content hashing (fix #2)
# --------------------------------------------------------------------------- #
def _digest(chunks: list[bytes]) -> str:
    h = hashlib.sha256()
    for chunk in chunks:
        # Length-prefix each chunk so concatenation is unambiguous.
        h.update(str(len(chunk)).encode("ascii"))
        h.update(b"\x00")
        h.update(chunk)
    return f"{_HASH_PREFIX}:{h.hexdigest()[:_HASH_LEN]}"


def _canonical_bytes(data: Any) -> bytes:
    """Deterministic JSON encoding (sorted keys) for semantic hashing."""
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


# --------------------------------------------------------------------------- #
# Contract 1 — Task
# --------------------------------------------------------------------------- #
class Task(BaseModel):
    """A single office-work task, authored by hand as ``task.yaml``."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, description="e.g. 'T01-inbox-triage'")
    title: str = Field(..., min_length=1)
    category: Category
    difficulty: Difficulty
    prompt: str = Field(..., min_length=1)
    artifacts: list[str] = Field(
        default_factory=list,
        description="Filenames under the task's artifacts/ directory.",
    )
    tools_allowed: list[str] = Field(default_factory=list)
    author_notes: str | None = None
    #: Set by the runner from :func:`hash_task_dir`; never authored by hand.
    content_hash: str | None = None

    @field_validator("artifacts", "tools_allowed")
    @classmethod
    def _no_blank_entries(cls, v: list[str]) -> list[str]:
        if any(not str(item).strip() for item in v):
            raise ValueError("list entries must be non-empty strings")
        return v


# --------------------------------------------------------------------------- #
# Contract 2 — Rubric
# --------------------------------------------------------------------------- #
class Criterion(BaseModel):
    """One weighted rubric criterion with 1/3/5 scoring anchors."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    weight: float = Field(..., gt=0.0, le=1.0)
    description: str = Field(..., min_length=1)
    #: Anchors for scores 1, 3, and 5 — what each level concretely looks like.
    anchors: dict[int, str]

    @field_validator("anchors")
    @classmethod
    def _require_1_3_5(cls, v: dict[int, str]) -> dict[int, str]:
        if set(v) != {1, 3, 5}:
            raise ValueError(f"anchors must define exactly scores 1, 3 and 5; got {sorted(v)}")
        if any(not str(text).strip() for text in v.values()):
            raise ValueError("each anchor must be a non-empty description")
        return v


class Rubric(BaseModel):
    """The weighted grading contract for one task (``rubric.yaml``)."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(..., min_length=1)
    criteria: list[Criterion] = Field(..., min_length=1)
    #: Conditions that force a score of 0 regardless of criteria (e.g. fabricated data).
    auto_fail: list[str] = Field(default_factory=list)
    #: Set from :func:`hash_rubric`; never authored by hand.
    content_hash: str | None = None

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> Rubric:
        total = sum(c.weight for c in self.criteria)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"criterion weights must sum to 1.0 (got {total:.4f})")
        names = [c.name for c in self.criteria]
        if len(names) != len(set(names)):
            raise ValueError("criterion names must be unique")
        return self


# --------------------------------------------------------------------------- #
# Contract 3 — RawResult
# --------------------------------------------------------------------------- #
class SamplingParams(BaseModel):
    """Sampling settings used for a run (fix #3).

    ``None`` means "use the provider's default", which is the recommended v1
    policy: DeskBench reports variance under vendor-default settings, the
    deployment-realistic condition an office user actually experiences.
    """

    model_config = ConfigDict(extra="forbid")

    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    seed: int | None = None
    source: Literal["vendor-default", "explicit"] = "vendor-default"


class ToolCall(BaseModel):
    """One entry in a run's tool trace (only the 2 tool-using v1 tasks populate this)."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: str | None = None


class RawResult(BaseModel):
    """One (task, model, run) execution captured by the runner."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(..., min_length=1)
    model_id: str = Field(..., min_length=1)
    run_index: int = Field(..., ge=0)
    output: str
    tool_trace: list[ToolCall] = Field(default_factory=list)
    tokens_in: int = Field(0, ge=0)
    tokens_out: int = Field(0, ge=0)
    latency_s: float = Field(0.0, ge=0.0)
    #: Free-tier models cost $0 — recorded explicitly, and we say so in the report.
    cost_usd: float = Field(0.0, ge=0.0)
    timestamp: datetime
    error: str | None = None
    #: Sampling settings this run used (fix #3).
    sampling: SamplingParams = Field(default_factory=SamplingParams)
    #: Content hash of the task dir this run was produced against (fix #2).
    task_hash: str = Field(..., min_length=1)

    @property
    def record_id(self) -> str:
        return record_id(self.task_id, self.model_id, self.run_index)


# --------------------------------------------------------------------------- #
# Contract 4 — Score
# --------------------------------------------------------------------------- #
class CriterionScore(BaseModel):
    """The judge's score and rationale for a single rubric criterion."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    score: int = Field(..., ge=1, le=5)
    judge_rationale: str = Field(..., min_length=1)


class Score(BaseModel):
    """The graded result for one RawResult (``results/scores/<record>.json``)."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(..., min_length=1)
    model_id: str = Field(..., min_length=1)
    run_index: int = Field(..., ge=0)
    criterion_scores: list[CriterionScore] = Field(..., min_length=1)
    weighted_total: float = Field(..., ge=0.0, le=5.0)
    auto_fail_triggered: bool = False
    judge_model: str = Field(..., min_length=1)
    #: Failure modes, human-assigned in v1 (fix #5). Empty for passing outputs.
    failure_modes: list[FailureMode] = Field(default_factory=list)
    #: Hashes pinning the exact task and rubric versions graded (fix #2).
    task_hash: str = Field(..., min_length=1)
    rubric_hash: str = Field(..., min_length=1)
    timestamp: datetime

    @property
    def record_id(self) -> str:
        return record_id(self.task_id, self.model_id, self.run_index)


# --------------------------------------------------------------------------- #
# Record addressing
# --------------------------------------------------------------------------- #
def record_id(task_id: str, model_id: str, run_index: int) -> str:
    """Content-addressed filename stem: ``{task_id}__{model_id}__run{n}``.

    The model id is slugified (``/`` and ``:`` -> ``-``) so provider-prefixed
    ids like ``gemini/gemini-1.5-flash`` stay filesystem-safe.
    """
    safe_model = model_id.replace("/", "-").replace(":", "-")
    return f"{task_id}__{safe_model}__run{run_index}"


# --------------------------------------------------------------------------- #
# Loaders (readable errors for hand-authored YAML)
# --------------------------------------------------------------------------- #
def _load_yaml(path: Path) -> Any:
    try:
        with Path(path).open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise SchemaError(f"{path}: not valid YAML: {exc}") from exc


def load_task(path: str | Path) -> Task:
    """Load and validate a ``task.yaml``, raising :class:`SchemaError` on failure."""
    path = Path(path)
    data = _load_yaml(path)
    if not isinstance(data, dict):
        raise SchemaError(f"{path}: expected a YAML mapping, got {type(data).__name__}")
    try:
        return Task.model_validate(data)
    except ValidationError as exc:
        raise SchemaError(f"{path}: invalid task definition:\n{exc}") from exc


def load_rubric(path: str | Path) -> Rubric:
    """Load and validate a ``rubric.yaml``, raising :class:`SchemaError` on failure."""
    path = Path(path)
    data = _load_yaml(path)
    if not isinstance(data, dict):
        raise SchemaError(f"{path}: expected a YAML mapping, got {type(data).__name__}")
    try:
        return Rubric.model_validate(data)
    except ValidationError as exc:
        raise SchemaError(f"{path}: invalid rubric definition:\n{exc}") from exc


# --------------------------------------------------------------------------- #
# Content-hash versioning (fix #2)
# --------------------------------------------------------------------------- #
def hash_task_dir(task_dir: str | Path) -> str:
    """Stable content hash over a task directory: prompt + artifact bytes + reference.

    The hash depends on the task's *semantic* content (the validated task fields,
    minus the hash itself), the raw bytes of every declared artifact, and the
    reference answer. Reformatting comments or reordering YAML keys does not
    change it; changing the prompt, an artifact, or the reference does. A missing
    declared artifact is a :class:`SchemaError`.
    """
    task_dir = Path(task_dir)
    task = load_task(task_dir / "task.yaml")

    semantic = task.model_dump(exclude={"content_hash"}, mode="json")
    chunks: list[bytes] = [b"task", _canonical_bytes(semantic)]

    artifacts_dir = task_dir / "artifacts"
    for name in sorted(task.artifacts):
        artifact_path = artifacts_dir / name
        if not artifact_path.exists():
            raise SchemaError(
                f"{task_dir}: declared artifact '{name}' not found at {artifact_path}"
            )
        chunks.append(f"artifact:{name}".encode())
        chunks.append(artifact_path.read_bytes())

    reference_path = task_dir / "reference.md"
    if reference_path.exists():
        chunks.append(b"reference")
        chunks.append(reference_path.read_bytes())

    return _digest(chunks)


def hash_rubric(rubric: Rubric | str | Path) -> str:
    """Stable content hash over a rubric's semantic content.

    Accepts an already-loaded :class:`Rubric` or a path to a ``rubric.yaml``.
    Hashing the validated model (not the file bytes) means whitespace and comment
    changes do not bump the version, but any change to criteria, weights,
    anchors, or auto-fail conditions does.
    """
    if not isinstance(rubric, Rubric):
        rubric = load_rubric(rubric)
    semantic = rubric.model_dump(exclude={"content_hash"}, mode="json")
    return _digest([b"rubric", _canonical_bytes(semantic)])
