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

---

## 2026-07-11 — Step 2: Model registry

**Built.**

- `config/models.yaml` — four leaderboard models, one per lab, all free-tier:
  `gemini-flash` (`gemini/gemini-2.0-flash`), `glm-4.7-flash`
  (`openai/glm-4.7-flash` via Z.ai base URL), `llama-3.3-70b`
  (`groq/llama-3.3-70b-versatile`), `deepseek-v3-free`
  (`openrouter/deepseek/deepseek-chat-v3-0324:free`). Each entry carries the
  litellm model string, provider label, `api_key_env` (env-var *name* only), and
  `sampling: {source: vendor-default}` (fix #3). Plus a held-out `judge:` entry.
- `deskbench/registry.py` — `load_registry()` validates the YAML into
  `ModelConfig` objects (`extra="forbid"`, readable `ConfigError`). Retry/backoff
  (tenacity: `stop_after_attempt` + `wait_exponential`, retrying only transient
  provider errors matched by class name) and the on-disk `ResponseCache` are
  built **now**, not later. Cache key = `(model_id, task_hash, sampling_params,
  run_index)` (**fix #4**). LiteLLM is imported lazily inside `_raw_completion`
  so the module (and tests) import with no provider SDKs and no network.
- `deskbench/cli.py` (Typer) — `deskbench models` (list registry, no network) and
  `deskbench ping` (one live call per provider; bypasses cache; exits non-zero on
  any failure, so it doubles as a smoke test). Wired `deskbench` as a console
  entry point in `pyproject.toml` now that `cli.py` exists.
- `tests/test_registry.py` (20 tests, all network mocked): loading + judge
  independence (rejects a judge that shares an id *or* model string with a
  leaderboard entry, and configs with <4 models or no judge); cache-key
  properties; retry-on-transient vs no-retry-on-hard-error; missing-key failure
  that never touches the network. Headline: `test_two_runs_of_same_task_can_differ`
  proves run 0 and run 1 get distinct cache keys and therefore CAN differ (fix #4
  regression), while a repeated identical run is served from cache.
- `docs/adding-a-model.md` — the one-line-to-add-a-model guide, sampling policy,
  and the judge-independence rule.

**What broke.**

- Judge-independence check was initially unreachable for the id-collision case:
  registering the judge hit the generic "duplicate model id" guard first. Moved
  the independence validation to run *before* registering the judge so the
  specific policy message ("must not be a leaderboard model") is what surfaces.
- Lint: Typer's declarative API calls `Option()` in argument defaults, which ruff
  flags as B008. Added a per-file ignore for `deskbench/cli.py` (this is the
  intended Typer pattern), plus removed an unused import and wrapped a long line.

**Decided — judge model choice (fix #1 / judge independence).**

- Judge = **Qwen2.5-72B-Instruct** (Alibaba) via OpenRouter free tier
  (`openrouter/qwen/qwen-2.5-72b-instruct:free`), held out of the leaderboard.
  Rationale: the four leaderboard models span the Google, Zhipu, Meta and
  DeepSeek families; Qwen is independent of all four, so it cannot self-prefer
  any leaderboard entry. It is the strongest free, family-independent option
  available. If free tiers ever force the judge to overlap a leaderboard family,
  the plan's fallback is an explicit self-preference check reported alongside the
  results (per BUILD_PLAN §3). The registry mechanically enforces independence,
  so this can't regress silently.
- Model strings are best-effort free-tier slugs. The maintainer will run
  `deskbench ping` with real keys to confirm each answers; any provider rename is
  a one-line fix in `models.yaml`.

**DoD.** `pytest` green (48 tests total); `config/models.yaml` has ≥4 models;
`deskbench models` lists the registry; `deskbench ping` ready for manual
key-backed verification. ✅

---

## 2026-07-11 — Step 3: Pilot tasks (T01, T02)

**Built.**

- **T01 — `tasks/T01-inbox-triage/`** (communication, medium). Artifacts:
  `inbox.md` (five real-sounding emails with timestamps) + `calendar.md`.
  Buried structure: the CEO's Mon 16:30 note ("move the board meeting to
  Thursday") *supersedes* her Mon 08:12 "board deck by Wednesday, top priority",
  so the true hard deadline becomes the client's Tue-noon SOW; and covering a
  colleague's 2pm call *clashes* with an existing 2–3pm CFO board-prep hold.
- **T02 — `tasks/T02-spreadsheet-reconciliation/`** (data-wrangling, hard).
  Artifacts: `crm_export.csv` + `finance_ledger.csv`. CRM total 43,650 (correct);
  finance total 38,550 because of two offsetting problems — a duplicated
  Bluecrest row (+8,400) and a dropped-zero on Everest (1,500 vs 15,000, −13,500)
  — net −5,100, verified to match. Everything else (name variants, `$`/decimal/
  thousands formatting, MM/DD vs DD/MM dates) is cosmetic noise. The task is to
  separate the one real error from the noise and flag the ambiguous value rather
  than confidently "fix" it. Arithmetic was checked programmatically.
- Both tasks follow the fixture pattern exactly (task.yaml + artifacts/ +
  reference.md + rubric.yaml) and schema-validate. Each rubric has weighted
  criteria summing to 1.0 with concrete 1/3/5 anchors and `auto_fail` conditions
  (fabrication; unacknowledged impossible actions).
- `tests/test_tasks.py` — CI now schema-validates **every** task dir on push
  (BUILD_PLAN §3): id matches dir, rubric task_id matches, reference.md present,
  declared artifacts exist, content hash computes, weights sum to 1.0.
- `scripts/saturation_check.py` + `tests/test_saturation.py` — a lightweight
  saturation probe (kept separate from the Step-5 grader): runs two models on
  both pilots, has the held-out judge score them against the rubric anchors, and
  prints the spread / flags saturation (all ≥4/5). Its pure helpers are
  unit-tested with no network; the live path needs keys.
- `docs/adding-a-task.md` — the task-authoring guide (reference-before-model
  discipline, how to make artifacts messy with a buried contradiction, writing
  anchored rubrics), written from authoring T01/T02.

**Discipline (stated as required).**

- **Both `reference.md` files were written before any model was run** — indeed
  before any model *could* be run in this environment (no provider keys here).
  This is the contamination-resistance + "decide what good means first"
  commitment from BUILD_PLAN §3, and it is trivially satisfied because no run has
  happened yet.

**Saturation check — status: PENDING maintainer run (needs keys).**

- The saturation check requires live provider keys, which are **not present in
  this build environment** (same reason `deskbench ping` is a manual step). I did
  **not** fabricate scores. The probe is built, tested, and ready:
  `python scripts/saturation_check.py` (defaults: `gemini-flash` +
  `llama-3.3-70b` across T01 and T02).
- Gate (unchanged, per BUILD_PLAN §3): if every (task, model) scores ≥4/5, the
  tasks don't discriminate → harden before scaling (Step 6). The build correctly
  stops at Step 3, so the gate is respected regardless: Step 4 does not begin
  here. Once the maintainer runs the probe, record the spread in the next
  BUILD_LOG entry; if saturated, harder variants are proposed before proceeding.
- Design intent to resist saturation: both tasks hinge on catching a buried
  contradiction and on *flagging* ambiguity rather than resolving it silently —
  behaviours weaker models routinely miss — so the expectation is a spread, not a
  ceiling. This is a hypothesis to confirm with the probe, not a claim.

**DoD.** Two task dirs schema-validate (CI-enforced); saturation check built,
tested, and logged (live run pending keys). ✅ *(machine-checked criteria met;
saturation numeric result deferred to the maintainer's key-backed run.)*

---

## 2026-07-11 — Step 4: Runner (mocked)

*Sequencing note: the maintainer moved the key-dependent work (ping, saturation,
T01/T02 editorial pass) to a hard gate BEFORE Step 6, and asked for Steps 4 and 5
to be built now, fully mocked. So this runner is built and tested with no live
API calls; the gate still governs Step 6.*

**Built.**

- `deskbench/runner.py` (Box 3) — `run_task(registry, task_dir, model_id,
  n_runs)` inlines the task's artifacts into one self-contained prompt
  (`build_prompt`), calls the cached/retried registry, and writes a validated
  `RawResult` JSON per run to `results/raw/{task}__{model}__run{n}.json`.
  - **Errors are results, not crashes:** a provider exception is captured into
    `RawResult.error` with empty `output`; a sweep never aborts on one bad call.
  - **Resumable:** an existing *successful* run is loaded and skipped (no
    re-bill); an *errored* run is retried on resume. With the registry's per-run
    cache, reruns cost zero calls.
  - **Tool containment:** a task declaring `tools_allowed` is rejected with a
    clear message (the two tool tasks arrive later; the pilots are
    self-contained). This is an explicit boundary, not a stub.
- `deskbench run --task … --model … -n …` CLI (Typer): fans out over tasks ×
  models, prints per-cell run/error counts, exits non-zero if any run errored.
- Refactor: `build_prompt` now lives in `runner.py` and `scripts/saturation_check.py`
  imports it (removed the duplicate).
- `tests/test_runner.py` (13 tests, all mocked): N valid JSONs written;
  provider error captured as a result; resume skips completed / retries errored;
  `--no-resume` re-runs; tool task rejected; selector resolution; prompt inlining;
  and the committed fixture validates.
- `tests/fixtures/sample_raw_result.json` — a real `RawResult` (generated via the
  schema so it is guaranteed valid), committed as the Step 4 fixture.

**What broke.**

- Lint: `datetime.now(timezone.utc)` → `datetime.now(UTC)` (ruff UP017); an unused
  loop index in a test (B007). Both auto-fixed.

**Decided.**

- On resume, only *successful* runs are skipped; *errored* runs are retried. An
  interrupted or rate-limited sweep thus heals itself on the next invocation
  rather than freezing a transient failure into the record.
- The judge/grading path is deliberately **not** in the runner — the runner only
  produces raw model outputs. Grading is Box 4 (Step 5).

**DoD.** `pytest` green (69 tests total); `tests/test_runner.py` passes; a raw
result JSON is committed as a fixture; runner is resumable. ✅

---

## 2026-07-11 — Step 5: Grader (mocked)

**Built.**

- `deskbench/grader.py` (Box 4) — grades a model output against its rubric via
  the **held-out judge**:
  - `build_judge_prompt` assembles rubric anchors + auto-fail conditions +
    reference (explicitly demoted to "context only, NOT the grading target") +
    the candidate answer, and instructs the judge to score against the anchors
    and cite the anchor in each rationale.
  - `parse_judge_response` enforces a strict JSON contract: every criterion
    scored 1-5 with a non-empty rationale; unknown / missing / duplicate criteria
    and out-of-range scores are rejected (`JudgeParseError`).
  - `grade()` does **reject-and-retry** (default 3 attempts); persistent failure
    raises `GraderError` rather than emitting a fabricated score. The judge cache
    seed encodes the exact candidate + rubric hash so grades of different outputs
    never collide, and `run_index=attempt` gives a fresh call on each retry.
  - **Auto-fail forces the weighted total to 0.0.** Failure-mode taxonomy is
    left to Step 7 (human-assigned, fix #5), so `Score.failure_modes` stays empty.
- `deskbench grade` CLI: walks `results/raw/`, grades matching results, writes
  `results/scores/{record}.json`; skips errored raws; reports auto-fails and
  parse failures; exits non-zero if any grade failed to parse.
- `tests/test_grader.py` (16 tests, judge fully mocked): valid grading +
  weighting; auto-fail → 0; reject-and-retry recovers on a later attempt;
  persistent bad JSON raises; the full JSON contract (missing/unknown/duplicate/
  out-of-range/empty-rationale/non-JSON/prose-wrapped); grading uses **only** the
  held-out judge (asserted via the captured model id) which is not a leaderboard
  model; end-to-end via a RawResult; and the committed score fixture validates.
- `tests/fixtures/sample_score.json` — a real `Score` (generated via the schema,
  guaranteed valid), committed as the Step 5 fixture.
- `docs/adr/ADR-002-judge-prompt-and-independence.md` — judge prompt design
  (anchors-not-reference, cite-the-anchor, enforced JSON, reject-and-retry,
  auto-fail) and the judge-independence policy incl. the self-preference fallback.

**What broke.**

- Lint: two over-long lines and a `timezone.utc` (UP017). While fixing, I
  lower-cased the whole judge prompt in one assertion, which then broke the
  `"AUTO-FAIL"`/`"score 5:"` substring checks — corrected to keep a
  case-preserving copy for those and a lower-cased copy only for the
  case-insensitive check.

**Decided.**

- **Judge output must be structured and enforced, never parsed from prose.** A
  strict per-criterion JSON schema is what makes rationales auditable and feeds
  the Step 7 human-agreement check; the price is occasional reject-and-retry.
- **The grader never invents a score.** If the judge won't produce valid JSON in
  the attempt budget, that result is left ungraded and surfaced — an
  unparseable judge reply is an honest failure, not a silent zero.

**DoD.** `pytest` green (85 tests total); `tests/test_grader.py` passes; a score
JSON fixture validates; spot-checkable rationales cite the rubric anchors (the
judge prompt mandates it, and the parser rejects empty rationales). ✅

---

### ⛔ HARD GATE before Step 6 (maintainer, key-dependent)

Per the maintainer's instruction, Steps 4 and 5 were built fully mocked (no live
API calls). **Step 6 does not start until the gate has real numbers:**

1. `deskbench ping` — confirm all four model slugs + the judge resolve with real
   keys; any provider rename is a one-line fix in `config/models.yaml`.
2. `python scripts/saturation_check.py` — run the pilots against two models and
   paste the score spread. If everything scores ≥4/5, harder task variants are
   proposed before scaling.
3. The maintainer's editorial pass on T01/T02 (applied verbatim when received,
   recorded here as maintainer editorial changes).

The build stops at Step 5 and waits.

---

## 2026-07-11 — MVP pivot: `variant` field (messy | clean)

*Change of plan (maintainer): descope to a 2-day MVP — "DeskBench Pilot": 2 tasks
(T01, T02) × 2 variants (messy + clean twin) × 4 models × 3 runs, judge-graded
with 100% human validation, reporting leaderboard + MESS PENALTY + SILENT-FAILURE
RATE + judge–human agreement. The 12-generator vision moves to the roadmap
(ADR-002 stays as the v2 design; the framework is NOT built now). Steps 4 and 5
(runner, grader) were already built and committed earlier this session; the only
net-new code for item 1 is the variant field.*

**Built.**

- `schemas.py`: new `Variant = Literal["messy", "clean"]`. Added `variant` to
  **Task** (source of truth; defaults to `messy` so existing task.yaml stay valid;
  clean twins declare `variant: clean`) and to **RawResult** (recorded per run so
  the analyzer can pair twins without relying on a naming convention).
- `runner.py`: `run_once` now stamps `RawResult.variant = task.variant` on both
  the success and error paths.
- Tests: `test_schemas.py` — variant defaults to messy, accepts clean, rejects an
  invalid value, and round-trips on RawResult; `test_runner.py` — the runner
  records `messy` for T01 and `clean` for a clean-twin task dir. 88 tests green,
  lint clean.

**Decided.**

- `variant` lives on both Task (declared) and RawResult (recorded). This is the
  same concept materialized where it belongs; it keeps the runner trivial (copy
  `task.variant`) and avoids inferring the twin from an `id` suffix.

**Not yet done / blocked (see BLOCKERS below).** Clean twins (T01c, T02c) and the
CORE/MESS rubric split are NOT authored in this commit — they depend on a
maintainer input (the core/noise "addendum") and a rubric-weighting decision that
conflicts with the current schema. Raised for resolution before authoring.

### ⛔ BLOCKERS raised before authoring the clean twins (item 2)

1. **The "addendum" is not in hand.** The plan says author the twins "per the
   core/noise definition in the addendum" — that document wasn't provided. The
   inline definition (T01c: drop the superseded-instruction trap + calendar
   clash; T02c: keep dup row + dropped zero, strip format/name/date noise) is
   enough to draft from, but the exact CORE-vs-MESS *criterion* split is the
   maintainer's curation call.
2. **CORE/MESS weights conflict with the schema.** "CORE criteria shared with
   identical weights across twins; MESS criteria messy-only" cannot hold while the
   Rubric schema requires weights to sum to 1.0: if core weights are identical in
   both twins, the clean rubric (core only) sums to < 1.0. Resolving this needs a
   schema + grader change, so it must be confirmed before authoring, not guessed.

Nothing runs and no twins are authored until these are resolved.

---

## 2026-07-11 — MVP item 2a: CORE/MESS rubric mechanics (blockers resolved)

*Maintainer resolved both blockers: the "addendum" is the inline core/noise
definition in the MVP plan (T01c drops the superseded-instruction trap and the
calendar clash; T02c keeps both real discrepancies and strips format/name/date
noise), with the editorial pass as the curation check; and the CORE/MESS weight
rule is implemented exactly as stated — identical core weights across twins.*

**Built.**

- `schemas.py`:
  - `Criterion.kind: "core" | "mess"` (default `core`). CORE grades the
    underlying work and appears in both twins under the same name with
    **identical weights**; MESS grades handling of the injected noise and exists
    only in the messy rubric.
  - `Rubric.variant: "messy" | "clean"` (default `messy`). Messy rubrics keep
    the weights-sum-to-1.0 invariant unchanged. Clean rubrics may contain ONLY
    core criteria and their weights — the messy twin's core weights verbatim,
    NOT renormalized — must sum to ≤ 1.0.
  - `Task.twin_of` — a clean twin names its messy original explicitly, so the
    analyzer pairs twins without naming-convention inference. Validators: only
    clean tasks may set it, and never to themselves.
- `grader.py`: `weighted_total` now divides by the rubric's weight sum. For
  messy rubrics (sum = 1.0) this changes nothing; for clean rubrics it puts the
  core-only total on the same 1–5 scale, so twin totals are directly comparable
  and the mess penalty (mean core-criteria score difference) is well-defined.
- Tests: 7 new schema tests (kind default/rejection; clean-rubric rules; the
  messy invariant unchanged; twin_of constraints) + a grader test proving the
  clean-rubric normalization ((5·0.30 + 1·0.10)/0.40 = 4.0, not 1.6). 95 green.

**Decided.**

- Weight semantics follow the maintainer's words literally: core weights are
  identical across twins and the *grader* normalizes, rather than renormalizing
  the clean rubric's YAML. The YAML stays the shared source of truth and the
  cross-twin identity is machine-checkable.
- Schema field additions (`kind`, `variant`, `twin_of`) shift task/rubric
  content hashes. No runs exist yet, so nothing is invalidated; hashes freeze
  at the pilot run.

---

## 2026-07-11 — MVP item 2b: clean twins T01c and T02c (hand-authored)

**Built.**

- **Rubric splits on the messy originals** (curation, per the inline core/noise
  definition — maintainer reviews at the editorial STOP):
  - T01: CORE = correct-prioritization (0.30), surfaces-not-silently-resolves
    (0.15), reply-quality (0.10). MESS = catches-superseded-instruction (0.25),
    catches-scheduling-conflict (0.20).
  - T02: CORE = correct-reconciled-total (0.30), finds-duplicate (0.15),
    flags-ambiguity-not-guesses (0.15), discrepancy-list-quality (0.10).
    MESS = identifies-real-vs-cosmetic (0.30).
- **`tasks/T01c-inbox-triage/`** — clean twin of T01. Removed: the Mon 16:30
  supersession email (the Wednesday deck deadline simply stands) and the
  14:00–15:00 CFO board-prep hold (Sam's 2pm cover now fits). Core preserved:
  the SOW (Tue 12:00, external, irreversible) is still today's #1 ahead of the
  deck; the expense-reminder ambiguity still needs a stated assumption; both
  replies still owed. Difficulty: easy (was medium).
- **`tasks/T02c-spreadsheet-reconciliation/`** — clean twin of T02. KEPT both
  genuine problems: duplicated Bluecrest row 1002 (+8,400) and Everest 1,500
  vs 15,000 (−13,500) → CRM 43,650 vs finance 38,550, net −5,100, verified
  programmatically to match the messy twin exactly. Removed: every cosmetic
  difference (names identical, ISO dates in both files, one number format).
  Difficulty: medium (was hard).
- **Prompts are byte-identical across each twin pair** (CI-enforced): the only
  thing that changes between variants is the artifacts. The prompt still asks
  for conflict/cosmetic classification, so the clean twins also measure
  noise-*invention* — a model that fabricates conflicts or cosmetic findings in
  clean materials fails the same discipline the messy twin tests. Both clean
  references say "none exist" explicitly.
- **`tests/test_tasks.py` twin invariants (CI-enforced):** every clean task
  declares `twin_of` resolving to a real messy dir; categories match; prompts
  byte-identical; the clean rubric's criteria == the messy rubric's core set
  with **identical weights**; every messy rubric has ≥1 mess criterion; rubric
  variant matches task variant. 100 tests green.

**Decided (flagged for the editorial pass).**

- Clean-twin difficulties were re-labeled honestly (easy/medium) since the traps
  are gone; pairing uses `twin_of`, so differing difficulty labels don't affect
  the mess-penalty computation.
- T02c keeps distinct header names (Deal ID/Txn etc.) — two-systems framing is
  core premise, not noise. The clean pair's cells are value-identical.
- Both reference.md files written before any model run, as always.

---

## 2026-07-11 — MVP item 2c: BUILDSEQUENCE descoped to the pilot

**Built.**

- BUILDSEQUENCE steps 6–10 rewritten to the MVP definitions (original text in
  git history): 6 = clean twins + twin invariants; 7 = the 48-run pilot matrix,
  raw + judge-scored; 8 = 100% human grading ingested + summary.json with the
  four pilot findings (leaderboard, mess_penalty, silent_failure, agreement)
  plus variance; 9 = single static dashboard (four charts + run inspector);
  10 = pilot REPORT.md with "What these results do NOT show" (n=2 first) and
  the pilot-framed README.
- `scripts/build_status.py` predicates updated to match: `twin_suite_validates`
  (≥2 valid clean/messy pairs, linked via twin_of), `pilot_run_complete`
  (≥48 raw + ≥48 scores under results/), `human_grades_ingested`,
  `summary_mvp_complete`. The certifier's own tests extended (twin predicate
  true on the real repo; pilot-run predicate false before any run). 102 tests.

**Decided.**

- Step 7's DoD counts result files under `results/`, which are currently
  gitignored — so that step can only flip ✅ once the pilot results are
  committed (or the ignore policy is revisited). Raised as an explicit
  maintainer question at the editorial STOP, not decided unilaterally.

---

## 2026-07-16 — Docs-alignment commit (external audit)

*An external audit ([DESKBENCH_AUDIT.md](DESKBENCH_AUDIT.md), 2026-07-16, now
committed at the repo root) found the code healthy (102/102 tests, honest
ledger) but the planning docs describing the pre-pivot 12-static-task design
while the code implements the MVP pilot (F1), the v2 generator ADR never
written (F2), and Step 3's predicate weaker than its DoD text (F3). This
commit fixes all three; docs only, no pipeline code.*

**Built.**

- **F1 — planning docs rewritten to the shipped pilot scope.** BUILD_PLAN.md,
  PRD.md, and DASHBOARD_SPEC.md now describe: 2 twin pairs × 4 models × 3 runs
  (48 completions), CORE/MESS rubric split, mess penalty per methodology.md's
  formula, silent-failure rate (human-assigned), 100% human validation, and
  the committed-results evidence policy. The 12-task/generator vision moved to
  a clearly-marked Roadmap section in BUILD_PLAN (not deleted); the dashboard
  spec descoped to the four pilot charts + run inspector (original 8-section
  spec noted as living in git history). README opening and roadmap fixed NOW
  rather than at Step 10: "2 task pairs", pilot-honesty tone, n=2 named in the
  opening bullets.
- **F2 — `docs/adr/ADR-003-benchmark-as-a-function.md`** (Proposed, v2): task
  templates as seeded functions whose parameter draws change the correct
  answer; references computed, not written; core/noise as a parameter axis
  (clean twin = `noise=off`); anchor parity by construction; the provable
  contamination claim (fresh draw defeats memorized instances). Plus the
  honest risk, stated as a first-class section: shallow parameter diversity
  makes it a gimmick — with mitigations (structural not surface parameters,
  cross-draw diversity audit + effective-n reporting, human-graded samples of
  generated references, templates generalized only from audited pilot tasks).
- **F3 — Step 3's predicate now matches its DoD.** Chose the predicate route
  (keeps "statuses can't lie" true): new `saturation_recorded` predicate greps
  BUILD_LOG for a line starting `SATURATION RESULT:` (convention documented in
  BUILDSEQUENCE). Step 3 will regress to 🟨 on this push — honest and intended
  — until the maintainer runs the probe and records the line. Certifier tests
  updated: the ordering test now allows ✅ steps after a regressed 🟨
  predecessor (tightening a DoD must not unwind later verified work), and new
  tests pin the marker convention (a promise is not a result; inline mentions
  don't count).

**Decided.**

- Honest regression is a feature: strengthening a DoD retroactively flips the
  table to current truth rather than preserving a flattering history. Recorded
  in BUILDSEQUENCE rule 1.
- The audit itself is committed at the repo root — the work sample should show
  its own inspection, not just survive it.

---

## 2026-07-11 — MVP item 3: methodology.md, results-commit policy, mechanic flag

*Maintainer sent the addendum (core/noise + silent-failure defs + mess-penalty
formula) and confirmed three judgment calls: (1) anchor wording may adapt per
variant, with a comparability caveat; (2) difficulty relabels T01c=easy,
T02c=medium; (3) un-ignore results/{raw,scores,human} for the pilot. This entry
records the non-task-dir work done in response; the task dirs themselves are left
untouched for the maintainer's editorial pass.*

**Built.**

- `docs/methodology.md` — the scientific heart of the pilot: grading philosophy
  (anchors-not-reference, judge independence → ADR-002); reference-before-model
  discipline; the twin design with the **per-task core/noise asymmetry** (T01's
  traps ARE the mess → T01c measures baseline triage; T02's errors ARE core →
  T02c keeps both discrepancies); the **mess-penalty formula** (core-weight-
  weighted mean of per-criterion deltas over shared *relative* core weights, sign
  = clean − messy, never a difference of weighted_totals); the **cross-variant
  comparability caveat** (equal anchor strictness is a curation judgement); the
  **silent-failure definition** (flagged only if the output signals uncertainty
  on the *specific* wrong point — generic hedging doesn't count; human-assigned,
  never the judge in v1); 100% human judge validation; and an n=2 limitations
  pointer.
- **Results-commit policy (confirmation 3).** Un-ignored `results/{raw,scores,
  human}` in `.gitignore` and added `.gitkeep` to each so the full chain of
  evidence (48 outputs + judge scores + human grades) is committed for the pilot.
  The response **cache stays gitignored** — it's a mechanism, not evidence. This
  resolves the Step-7 DoD blocker noted in the item-2c entry. Done **before** the
  pilot run so history is clean.
- Confirmed already-correct from item 2b: difficulty relabels (T01c=easy,
  T02c=medium) and `twin_of` links are in place — no change needed.

**⚠️ Flagged for the editorial STOP — weight mechanic diverges from the addendum.**

- The committed twins implement **Option A**: clean rubrics keep the messy twin's
  core weights **byte-identical** (sum < 1.0), and `grader.weighted_total`
  normalizes by the weight sum. A CI invariant (`test_twin_pair_invariants`)
  enforces the absolute-weight identity.
- The addendum specifies **Option B**: "sum-to-1.0 kept, clean rubric
  **renormalizes** core weights." Option B keeps the schema invariant and needs
  no grader normalize, but stores ugly decimal weights and makes the twin
  invariant a relative-ratio check.
- **The two are numerically identical** for both the leaderboard and the mess
  penalty (which uses *relative* core weights either way). Reconciling A→B is a
  large, delicate rewrite of committed, actively-reviewed twin artifacts (schema
  + grader + both clean rubrics + the twin-invariant test + a grader test) for an
  identical result, so it was **not** done unilaterally. Raised for the
  maintainer to choose at the editorial STOP; `methodology.md` is written
  mechanic-neutral (relative core weights), so it holds under either choice.

**DoD.** 102 tests green; lint clean. Non-task-dir MVP items complete; task dirs
untouched pending editorial review.

---

## 2026-07-16 — Free-tier slug refresh (config/models.yaml only)

Providers renamed/repriced their free tiers out from under the registry; `ping`
was failing 4/5. Fixed in `config/models.yaml` **only** (standing rule); sampling
stays vendor-default; ids kept stable so fixtures/scripts referencing them don't
break. One line per slug change:

- **gemini-flash slug:** `gemini/gemini-2.0-flash` → `gemini/gemini-2.5-flash`.
  2.0-flash's free tier is now `limit: 0` (429 RESOURCE_EXHAUSTED); 2.5-flash's
  free tier answers. Verified by ping.
- **deepseek-v3-free slug + LEADERBOARD FAMILY CHANGE:**
  `openrouter/deepseek/deepseek-chat-v3-0324:free` →
  `openrouter/openai/gpt-oss-20b:free`. DeepSeek's `:free` variant went paid
  (404, "use the paid slug"); the OpenRouter models API (`/api/v1/models`) lists
  **no** DeepSeek `:free` at all. Per the fallback rule, picked a free model from
  a family that is not Google/Zhipu/Meta: **OpenAI gpt-oss-20b**. The four
  leaderboard labs are therefore now **Google / Zhipu / Meta / OpenAI** (was
  …/DeepSeek). Id `deepseek-v3-free` left unchanged (fixtures/scripts reference
  it); the id is now a historical label, not the family. Verified by ping.
- **qwen-2.5-72b-judge slug + JUDGE FAMILY CHANGE:**
  `openrouter/qwen/qwen-2.5-72b-instruct:free` →
  `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free`. Qwen2.5-72B lost its
  `:free` tier (404 → paid). Every remaining Qwen `:free` (qwen3-next-80b,
  qwen3-coder) is persistently upstream-rate-limited on OpenRouter (429, 8 rpm,
  0/3 on a reliability probe), so it is unfit for a judge that must grade every
  result. OpenRouter **does** have a suitable free judge, so NVIDIA NIM was not
  needed: **NVIDIA Nemotron-3-Ultra-550B** answered 3/3 on the same probe and is
  independent of all four leaderboard families (Google/Zhipu/Meta/OpenAI), so it
  cannot self-prefer. Judge family moves Qwen (Alibaba) → NVIDIA. Id
  `qwen-2.5-72b-judge` left unchanged (fixture `sample_score.json` references it);
  it is now a historical label. Verified by ping (~26 s latency — the 550B free
  endpoint is slow but reliable).
- **glm-4.7-flash:** NOT a config problem — `AuthenticationError` ("token expired
  or incorrect") is an expired ZAI key, being regenerated on z.ai. Left as-is.
  Double-checked its `base_url` points at z.ai's international endpoint
  (`https://api.z.ai/api/paas/v4`), **not** bigmodel.cn — correct, no change.

**Ping status:** 4/4 config-fixable models green (gemini-flash, llama-3.3-70b,
deepseek-v3-free, judge). glm-4.7-flash blocked on the maintainer's key
regeneration, not config. Holding at the gate.

---

## 2026-07-16 — Model-id rename to match served models (approved, pre-pilot)

Follow-up to the slug refresh above. The previous entry kept the ids stable
under the models.yaml-only rule, leaving `deepseek-v3-free` pointing at OpenAI
gpt-oss-20b and `qwen-2.5-72b-judge` pointing at NVIDIA Nemotron — dishonest ids
that surface in result filenames, the dashboard, and the report. Maintainer
approved a scoped override of the models.yaml-only rule to rename them **now**,
before the pilot — doing it after would re-key 96 result files.

- **`deepseek-v3-free` → `gpt-oss-20b-free`** and **`qwen-2.5-72b-judge` →
  `nemotron-judge`**. Updated every reference: `config/models.yaml` (ids +
  comments), `scripts/saturation_check.py` (docstring example), and
  `tests/fixtures/sample_score.json` (`judge_model`). `sample_raw_result.json`
  needed no change — its `model_id` is `gemini-flash`. No test hard-codes either
  id (assertions use `reg.judge_id` / dynamic ids), so none needed editing.

**DoD.** 104 tests green; ruff check + format clean. Ping re-run after the
rename: same 4/4 green, glm-4.7-flash still blocked on the key regen. Holding at
the gate.
