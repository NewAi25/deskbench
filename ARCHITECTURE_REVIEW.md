# DeskBench — Architecture Review

**Status:** Review complete — design sound, 5 required changes before build
**Date:** 2026-07-11
**Scope:** 8-box file-based pipeline, 7 Python modules (BUILD_PLAN.md, PRD.md, DASHBOARD_SPEC.md, BUILDSEQUENCE.md)

## Verdict

The architecture is appropriate for its scale and purpose. The core decision — a linear pipeline communicating only through typed files on disk — is the right call for ~600 result records, a single developer, $0 budget, and an audience that must be able to audit every number. It optimizes for the properties that matter here (reproducibility, inspectability, resumability) and correctly refuses the ones that don't (throughput, concurrency, serving infrastructure).

Five changes are required before build. One is strategic, four are contract-level.

## Dimension assessment

| Dimension | Rating | Notes |
|-----------|--------|-------|
| Fit to scale | Strong | 12×4×5 runs = trivial data volume; files > DB, no contest |
| Reproducibility | Strong* | *after fix #2 (versioning) — currently reruns can silently mix task versions |
| Coupling | Strong | schemas.py as single contract point; boxes replaceable independently |
| Resumability | Strong | content-addressed filenames + cache; interrupt-safe |
| Extensibility | Strong | new model = config line; new task = folder; both documented |
| Ecosystem awareness | **Weak** | no mention of existing eval frameworks — see fix #1 |
| Statistical honesty | Adequate | variance reported, but temperature policy undefined — fix #3 |
| Operational risk | Low | GitHub Action loop correctly guarded with markers + [skip ci] |

## Required changes

### 1. (Strategic) Acknowledge Inspect and justify building custom — ADR-000

The evals ecosystem has mature open-source harnesses: **Inspect** (UK AI Safety Institute), promptfoo, lm-evaluation-harness. Epoch's reviewers know these tools intimately. A custom pipeline with no mention of them reads as *unaware*, which is fatal in an evals work sample; the same pipeline with a one-page ADR-000 ("Why not Inspect?") reads as *deliberate*.

The honest justification, for the record: (a) the research contribution is tasks + rubrics + judge validation, not harness engineering — a ~1,000-line transparent pipeline keeps the full chain of evidence auditable in one sitting; (b) zero framework dependency means the repo runs untouched in five years; (c) building the loop yourself demonstrates you understand what harnesses do rather than what buttons they have. State also the counterargument (Inspect would give tool-sandboxing and log viewers for free) and note the roadmap option of porting tasks to Inspect format as a v2 interop gesture — that last point turns a perceived weakness into ecosystem fluency.

### 2. (Contract) Version-pin tasks and rubrics by content hash

Score JSONs record `rubric_version`, but nothing pins the *task* version, and versions are manual. If a task's artifacts or prompt change after a run, old raw results silently refer to a task that no longer exists — reproducibility breaks exactly where a reviewer would probe. Fix: `schemas.py` computes a content hash over each task dir (prompt + artifacts + reference) and each rubric; every raw result and score JSON embeds both hashes; the analyzer refuses to aggregate records whose hashes don't match the current suite (or flags them as stale). Cheap to build now, impossible to retrofit honestly.

### 3. (Contract) Define the temperature/sampling policy — it's a claims issue

The plan reports run-to-run variance as a finding, but never fixes sampling parameters. Variance at temperature 1.0 and variance at 0.2 are different claims. Decide once, record in `models.yaml` per model, embed in every raw result, state in methodology.md. Recommendation: providers' default temperature, documented — "variance under vendor-default settings" is the deployment-realistic claim, and it's what an office user experiences.

### 4. (Contract) Cache key must include run_index

The on-disk response cache exists to survive rate limits, but if keyed only on (model, prompt), runs 2 and 3 return run 1's cached response and all variance measurements collapse to zero — the pipeline would *appear* to work while quietly falsifying a headline metric. Key must be (model_id, task_hash, sampling_params, **run_index**). Add a regression test: two runs of the same task/model must be able to differ.

### 5. (Contract) Assign an owner to the failure-mode taxonomy

The taxonomy (hallucinated data / dropped constraint / false confidence / format failure / refusal / error) has no assigned classifier. If the LLM judge tags failure modes, that's a second judge task requiring its own validation; if the human does, it's a bounded manual pass. Recommendation for v1: **human-assigned** during the Step 7 grading pass (~60 sampled outputs, minutes each), judge-assigned deferred to v1.1 with its own agreement check. Update methodology.md accordingly.

## Options considered and rightly rejected

| Alternative | Why the plan's choice wins |
|---|---|
| SQLite/Postgres store | No concurrent writers, no queries files can't answer; DB hides the chain of evidence that files expose |
| Orchestrator (Airflow/Prefect) | 5-stage linear DAG run by one person; the CLI *is* the orchestrator |
| Streamlit/served dashboard | Hosting cost, link rot, server dependency — static HTML outlives them all |
| Building on Inspect | Defensible either way, but custom-with-ADR is stronger *for this repo's purpose* (see fix #1) |

## Consequences of this architecture

- **Easier:** auditing any number back to raw output; adding models/tasks; re-running one stage; reviewer trust.
- **Harder:** anything concurrent or continuous (fine — out of scope per PRD); rich agent sandboxing if v2 wants more tool-using tasks (that's the moment to reconsider Inspect).
- **Revisit when:** task count > ~50, more than one contributor writes results simultaneously, or v2 adds multi-step agent environments.

## Action items

1. [ ] Write ADR-000 "Custom pipeline vs Inspect" (Step 0, before any code)
2. [ ] Add content-hash versioning to schemas.py (Step 1)
3. [ ] Add sampling-params policy to models.yaml + methodology.md (Step 2)
4. [ ] Cache key includes run_index + regression test (Step 2)
5. [ ] Failure taxonomy: human-assigned in v1; note in methodology.md (Step 7)
