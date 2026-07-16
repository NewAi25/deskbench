# DeskBench — Codebase Audit

**Date:** 2026-07-16 · **Input:** `deskbench-main.zip` (snapshot Jul 11 23:53) · **Method:** full test-suite execution on Python 3.12, lint, build-status simulation, twin-arithmetic verification, ledger-vs-code and docs-vs-code cross-checks.

## Verdict in one paragraph

The code is in excellent shape and the ledger is honest: Steps 0–6 of 11 are done and verified (102/102 tests pass, ruff clean, the build-status simulation reproduces the committed table exactly, and T02/T02c twin arithmetic is programmatically identical: 43,650 vs 38,550 in both variants). Nothing in the pipeline is broken. The two real problems are elsewhere: **the planning documents no longer describe the project** (BUILD_PLAN, PRD, DASHBOARD_SPEC, and README contain zero mentions of mess penalty, silent-failure rate, or clean twins — they still describe the pre-pivot 12-static-task design, while BUILDSEQUENCE, methodology.md, and the code implement the MVP), and **the pilot has not run** — every remaining step is blocked on maintainer inputs (API keys, ping, saturation probe, editorial pass) that have been pending since Jul 11. The bottleneck is not code; it is you.

## Completion status

| Step | What | Status | Verified |
|---|---|---|---|
| 0–2 | Scaffolding, schemas, model registry | ✅ | tests pass; registry has 4 leaderboard models + held-out Qwen judge; cache keyed with run_index |
| 3 | Pilot tasks T01/T02 | ✅* | schema-valid; *but see F3 — saturation check never ran* |
| 4–5 | Runner, grader | ✅ | tests pass; raw/score fixtures committed; variant field threaded |
| 6 | Clean twins + CORE/MESS rubrics | ✅ | byte-identical prompts CI-enforced; identical core weights verified; arithmetic identical across T02 pair |
| 7 | Pilot run (48 results + judge scores) | ⬜ | `results/` is empty — **blocked on maintainer** (keys → ping → saturation → editorial pass → go) |
| 8 | Human validation + analyzer | ⬜ | `analyzer.py` does not exist yet (expected — needs Step 7 output) |
| 9 | Dashboard | ⬜ | `visualize.py` does not exist yet |
| 10 | Report + README reframe | ⬜ | not started |

**~64% by step count; the remaining code (analyzer, dashboard, report) is deliberately blocked behind the human gate.** CLI currently ships `models / ping / run / grade` — no `analyze / render` yet, consistent with the ledger.

## Findings

**F1 (medium — the top fix): planning-doc drift.** `BUILD_PLAN.md`, `PRD.md`, `DASHBOARD_SPEC.md`, and `README.md` contain **zero** occurrences of "mess penalty," "silent failure," "generator," or the twin design. They still specify the original 12-static-task benchmark; README's opening and roadmap still promise "12 tasks, 5 categories." Meanwhile BUILDSEQUENCE, methodology.md, and the code implement the MVP pilot. For a work sample whose thesis is meticulous, single-source-of-truth documentation — read by evals researchers — this contradiction is the most damaging thing in the repo. The "docs pivot" commit discussed in planning was evidently superseded by the MVP sprint and never landed.

**F2 (medium): the v2 roadmap centerpiece was never written.** The plan was to keep the "benchmark as a function" generator design as an ADR for the roadmap section of the report. No such ADR exists — ADR-002 was (reasonably) used for judge prompt/independence. Without it, Step 10's roadmap has nothing to point at, and the strongest idea in the project exists only in chat logs.

**F3 (low): Step 3's ✅ overstates its DoD.** The table's DoD text includes "saturation check logged in BUILD_LOG," but the machine predicate (`pilot_tasks_validate`) only checks that 2 task dirs validate. The saturation check itself has **never run** (BUILD_LOG honestly records "PENDING maintainer run — needs keys"). The repo's proudest mechanism — "statuses can't lie" — has one predicate weaker than its stated DoD. Fix either direction: reword the DoD text to what's actually checked, or add a predicate that greps BUILD_LOG for a recorded saturation result.

**F4 (info): the critical path is 100% maintainer inputs, stalled 5 days.** Keys were never provisioned (no ping recorded), the saturation probe never ran, and no editorial-pass entry exists in BUILD_LOG (the twins' anchors are still unreviewed by the maintainer). Every remaining ledger step is downstream of these. If the application deadline logic ("rolling — apply early") still holds, this stall is now the biggest risk to the whole project.

**No code defects found.** Suite green on 3.12 (repo requires ≥3.11), lint clean, no TODO/FIXME markers, status table reproducible, twin invariants hold, judge independence mechanically enforced in the registry, results-commit policy in place with cache correctly still ignored.

## Recommended next steps, in order

1. **Unblock yourself today (F4):** four free API keys into `.env` → `deskbench ping` → `python scripts/saturation_check.py` → editorial pass on the 4 task dirs. Roughly an hour of your time; everything else is waiting on it.
2. **Docs-alignment commit (F1 + F2 + F3):** rewrite BUILD_PLAN/PRD/DASHBOARD_SPEC to the pilot scope (or clearly mark superseded sections), fix README's opening/roadmap now rather than at Step 10, write ADR-003 "benchmark as a function (v2 roadmap)," and reconcile Step 3's DoD text with its predicate. Claude Code can do all of this without keys — it can run in parallel with item 1.
3. Then the gated sequence as planned: go → 48-run pilot → human grading → analyzer → dashboard → report → apply.

## Caveats

Audited a zip snapshot (no git history, so commit hygiene and CI runs weren't re-verified — CI workflows exist and the suite passes locally, which is the substance). Network-dependent paths (ping, saturation, pilot run) were not exercised — no keys in the audit environment, same as yours.
