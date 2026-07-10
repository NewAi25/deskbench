# DeskBench — Build Log

A dated log of every build step: what was built, what broke, and what was
decided. Written as the work happens, never backfilled. This log IS the
documentation story.

---

## 2026-07-11 — Step 0: Repo & scaffolding

**Built.**

- Repo structure per BUILD_PLAN.md §2: `deskbench/` package, `config/`,
  `tasks/`, `results/{raw,scores,human,tables}/`, `site/`, `report/`, `docs/`
  (with `adr/`), `scripts/`, `tests/`. Empty-until-later directories carry a
  `.gitkeep`; no stub Python modules were created (the "no placeholder code"
  rule), so `registry.py`, `runner.py`, etc. arrive in their own steps.
- `pyproject.toml` — Python ≥3.11, setuptools build. Runtime deps: litellm,
  pydantic v2, typer, pyyaml, tenacity, plotly. Dev extras: pytest, ruff,
  pre-commit. Ruff (line length 100, rules E/F/I/W/UP/B) and pytest config live
  here. The `deskbench` console entry point is intentionally *not* declared yet
  — it would point at `deskbench/cli.py`, which lands in Step 2; declaring a
  dangling entry point now would be placeholder wiring.
- `.env.example` — every provider key documented (Gemini, Groq, Z.ai,
  OpenRouter) with the free-tier URL and LiteLLM provider prefix for each. Keys
  are read from the environment only; `.env` is gitignored.
- `LICENSE` — MIT.
- `.pre-commit-config.yaml` — ruff + ruff-format, plus standard hygiene hooks
  (trailing whitespace, EOF, YAML check, large-file guard, private-key detector).
- `.github/workflows/ci.yml` — lint (ruff check + format --check) and tests
  (pytest on 3.11 and 3.12).
- `.github/workflows/build-status.yml` + `scripts/build_status.py` — the status
  table in BUILDSEQUENCE.md is a pure function of the repo's real state. The
  script checks each step's machine-checkable DoD (file existence, symbol
  presence, per-module pytest, task-dir schema validation) and rewrites only the
  Status column between the `STATUS:BEGIN/END` markers. The workflow commits any
  change back with `[skip ci]`. It is itself tested by
  `tests/test_build_status.py` (BUILDSEQUENCE rule 3: the certifier must be
  certified).
- `README.md` skeleton — pitch, Mermaid architecture diagram + box table,
  quickstart, live-status pointer, doc index, roadmap, MIT.
- `docs/adr/ADR-000-custom-pipeline-vs-inspect.md` — per ARCHITECTURE_REVIEW
  fix #1: acknowledges Inspect / promptfoo / lm-eval-harness and justifies the
  custom pipeline (research contribution is tasks+rubrics+judge-validation, not
  harness engineering; zero-dependency longevity; the counterargument and the
  v1.1 Inspect-export interop gesture are stated honestly).

**What broke.**

- `build_status.py`'s stdout summary printed status emoji, which crashed on the
  Windows cp1252 console (`UnicodeEncodeError`). The table write itself was fine
  (UTF-8, LF); only the log line failed. Fixed by printing the status *word*
  (`done`/`pending`/`progress`) instead of the glyph, keeping stdout ASCII-safe
  on legacy consoles while the file stays UTF-8.
- Added `.gitattributes` (`* text=auto eol=lf`) so the Linux CI auto-status
  commit never conflicts with Windows CRLF checkouts.

**Decided.**

- Empty scaffolding directories are tracked with `.gitkeep`, not with stub
  source files — keeps "no placeholder code" literally true.
- The status table is left in its all-`pending` state in this commit on purpose:
  the `build-status` workflow flips it automatically on push, which is the
  behavior we want to demonstrate rather than pre-bake by hand.

**DoD.** CI workflow present; `pyproject.toml`, `README.md`, `.env.example`
exist; `pytest` green locally (build-status tests). ✅

---

## 2026-07-11 — Step 1: Schemas

**Built.**

- `deskbench/schemas.py` — the four data contracts as pydantic v2 models, each
  with `extra="forbid"` so a typo in a hand-authored YAML key is a validation
  error, not a silently ignored field:
  - **Task** — id, title, category (5-value Literal), difficulty, prompt,
    artifacts, tools_allowed, author_notes, optional computed `content_hash`.
  - **Rubric** — task_id, criteria (each with 1/3/5 anchors), auto_fail,
    computed `content_hash`. Validators enforce weights summing to 1.0, unique
    criterion names, and anchors defined for exactly scores 1, 3 and 5.
  - **RawResult** — task_id, model_id, run_index, output, tool_trace,
    tokens/latency/cost, timestamp, error, plus **fix #3** (`SamplingParams`:
    temperature/top_p/max_tokens/seed, defaulting to `vendor-default`) and
    **fix #2** (`task_hash`).
  - **Score** — per-criterion score+rationale, weighted_total, auto_fail,
    judge_model, human-assigned `failure_modes` (fix #5 taxonomy as a Literal),
    plus `task_hash` and `rubric_hash` (fix #2).
- **Content-hash versioning (fix #2).** `hash_task_dir()` hashes a task's
  semantic content (validated task fields, minus the hash) + the raw bytes of
  every declared artifact + the reference; `hash_rubric()` hashes the validated
  rubric. Hashes are `sha256:<12hex>`. Reformatting a comment or reordering YAML
  keys does not move the hash; changing the prompt, an artifact, the reference,
  or any rubric weight/anchor does. A missing declared artifact is a
  `SchemaError`. This is the reproducibility guarantee ADR-001 relies on in
  place of database foreign keys.
- `load_task()` / `load_rubric()` wrap pydantic's `ValidationError` in a
  `SchemaError` prefixed with the file path, so a task author is pointed
  straight at the file and field to fix.
- `record_id()` — content-addressing (`{task_id}__{model_id}__run{n}`) with the
  model id slugified so provider-prefixed ids stay filesystem-safe.
- `tests/test_schemas.py` (21 tests) with fixtures under `tests/fixtures/`: a
  valid task dir (task.yaml + artifacts/emails.md + reference.md + rubric.yaml)
  and two deliberately malformed files — `task_malformed.yaml` (bad category +
  missing prompt) and `rubric_bad_weights.yaml`. The malformed-task test asserts
  the error is *readable*: it names the file and both broken fields (Step 1 DoD).
- `docs/adr/ADR-001-files-on-disk-over-database.md` — why files, not a DB
  (visible chain of evidence, trivial non-concurrent volume, stage isolation,
  longevity, diff-based review; integrity via content hashes rather than foreign
  keys).

**What broke.**

- Initial lint failures: unsorted imports, `datetime.timezone.utc` (ruff UP017
  prefers `datetime.UTC`), blind `pytest.raises(Exception)` (B017), and a couple
  of over-long lines. Fixed by tightening the tests to `pytest.raises(
  ValidationError)` and running `ruff --fix` + `ruff format`.

**Decided.**

- `difficulty` is a three-value Literal (`easy`/`medium`/`hard`). BUILD_PLAN
  names the field but does not enumerate it; three levels is the standard
  convention and keeps the value discriminating. Documented here as a chosen
  convention (reversible by widening the Literal) rather than an invented
  requirement.
- Rubric hashing operates on the *validated model*, not the file bytes, so
  formatting churn never bumps a rubric version — only semantic change does.

**DoD.** `pytest` green (28 tests total); a malformed `task.yaml` fails
validation with a readable error naming the file and fields. ✅
