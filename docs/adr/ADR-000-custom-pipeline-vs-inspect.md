# ADR-000 — Custom pipeline vs. Inspect (and other eval harnesses)

- **Status:** Accepted
- **Date:** 2026-07-11
- **Deciders:** DeskBench author
- **Context source:** ARCHITECTURE_REVIEW.md, required change #1 (strategic)

## Context

A mature open-source ecosystem for LLM evaluation already exists:

- **Inspect** (UK AI Safety Institute) — solvers, scorers, a sandboxed tool
  environment, and a polished log viewer.
- **promptfoo** — YAML-driven prompt/assertion testing.
- **lm-evaluation-harness** (EleutherAI) — the de-facto standard for academic
  multiple-choice / generative benchmarks.

Epoch AI's reviewers know these tools intimately. Building a custom pipeline
with no acknowledgement of them would read as *unaware* — a fatal signal in an
evaluation-research work sample. The question is not "custom vs. framework" in
the abstract; it is whether, **for this specific repo and its purpose**, a
~1,000-line transparent pipeline or an Inspect-based implementation better
serves the goal.

## Decision

Build a small custom file-based pipeline for v1, and record this decision
explicitly. Do **not** adopt Inspect (or promptfoo / lm-eval-harness) as the v1
harness.

## Rationale

1. **The research contribution is the tasks, the rubrics, and the judge
   validation — not harness engineering.** A transparent pipeline whose entire
   chain of evidence (task → raw output → judge rationale → aggregated number)
   can be audited in one sitting is worth more here than reusing a general
   engine whose internals a reviewer must trust. The differentiator DeskBench is
   showcasing is curation and grading judgment, and a custom loop keeps that
   judgment fully in view.

2. **Zero framework dependency means the repo runs untouched in five years.**
   Files-on-disk + LiteLLM has a tiny, stable surface. A benchmark's value is
   its longevity as a reference; minimizing moving parts protects that.

3. **Building the loop yourself demonstrates understanding, not button
   knowledge.** Writing the runner, the judge-JSON enforcement, and the
   content-hash versioning by hand proves fluency in *what* an eval harness
   does. That is the competency under assessment.

## Counterargument (stated honestly)

Inspect would give, for free:

- a **sandboxed tool-execution environment** — which DeskBench must implement
  carefully for the two tool-using tasks (BUILD_PLAN.md scopes this hard);
- a **log viewer** — DeskBench reimplements a slice of this as the dashboard's
  "run inspector";
- battle-tested **retry / concurrency** plumbing.

For a benchmark with heavy multi-step agent environments, those would tip the
decision toward Inspect. DeskBench v1 deliberately has only two tool-using tasks
(PRD non-goal: "complex multi-step agent environments"), so the sandboxing
benefit is small relative to the transparency cost.

## Consequences

- **Easier:** auditing any number back to a raw output; running any stage in
  isolation; reading the whole system in one sitting; no version-pinning of a
  third-party harness.
- **Harder:** rich agent sandboxing if a future version adds many tool-using
  tasks — that is the moment to reconsider Inspect.
- **Roadmap interop gesture:** v1.1 may add an exporter that emits DeskBench
  tasks in Inspect's task format. That turns a perceived "not invented here"
  weakness into demonstrated ecosystem fluency, and lets others run the suite in
  their preferred harness.

## Revisit when

- Task count grows past ~50, or
- v2 introduces multi-step agent environments needing real tool sandboxing, or
- more than one contributor needs to write results concurrently.

At any of those triggers, re-evaluate porting the runner onto Inspect while
keeping the tasks, rubrics, and judge-validation methodology unchanged.
