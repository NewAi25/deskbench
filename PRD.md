# DeskBench Pilot — PRD (one page)

## Problem
Public AI benchmarks over-index on exams and code. Almost none measure the messy, ambiguous, judgment-heavy tasks that make up real office work — and those that try rarely publish validated grading methods, and none isolate what the *mess itself* costs a model. Hiring managers, researchers, and practitioners have no grounded way to answer "can this model actually do desk work, and does realistic noise break it?"

## Goal
A small, open, rigorously graded **pilot** benchmark: 2 office tasks, each shipped as a **twin pair** (messy original + noise-stripped clean twin with a byte-identical prompt), run across 4 models × 3 runs (48 completions), judge-graded and **100% human-validated**, reporting four things — leaderboard, **mess penalty**, **silent-failure rate**, and judge–human agreement — from a fully reproducible $0 pipeline. The pilot exists to prove the method; scale comes from the v2 generator roadmap ([ADR-003](docs/adr/ADR-003-benchmark-as-a-function.md)).

## Users
1. **Primary:** AI-evals researchers and practitioners who want a grounded read on practical model capability — and a measured answer to "what does mess cost?"
2. **Secondary:** hiring reviewers (e.g., Epoch AI) assessing the author's evaluation-research ability — the repo is itself a work sample.
3. **Tertiary:** anyone adding a model or task (contribution path documented).

## Success criteria (pilot)
- 2 twin pairs (4 task dirs) with artifacts, pre-registered reference answers, and anchored CORE/MESS rubrics — twin invariants (byte-identical prompts, identical core weights) enforced in CI.
- 4 models × 2 variants × 3 runs = 48 completions, all judge-graded; judge–human agreement measured on **100%** of outputs and reported, whatever the number.
- Mess penalty and silent-failure rate computed per model from `results/` files only; every number reproducible from the committed chain of evidence.
- Score spread across models/variants (no saturation — probe recorded in BUILD_LOG before the run).
- Pipeline runs stage-by-stage from the CLI; adding a model = one config line.
- Public dashboard (four charts + run inspector) + report incl. "what these results do NOT show" (first limitation: n=2 tasks).
- Total API spend: $0.

## Non-goals (pilot)
- Scale (no 12-task suite — that moved to the v2 roadmap; 2 excellent twin pairs prove the method).
- The generator framework itself (designed in ADR-003, deliberately not built).
- Frontier-model coverage (free-tier models only; harness accepts any OpenAI-compatible endpoint later).
- Tool-using / multi-step agent tasks (both pilot tasks are self-contained; the runner rejects tool tasks explicitly).
- Localized/India-flavored task slice (v1.1 roadmap).
- Leaderboard-as-a-service, submissions, or hosting infrastructure.

## Key risks & mitigations
| Risk | Mitigation |
|---|---|
| LLM judge unreliable | Human-grade 100% at pilot scale, report agreement; iterate rubrics with before/after numbers kept |
| Judge self-preference | Judge (Qwen2.5-72B) family-independent of all 4 leaderboard models; independence enforced mechanically in the registry |
| Cross-variant anchors unequal in strictness | Named as a curation judgment in methodology.md; maintainer editorial pass reviews every pair against that standard |
| Tasks too easy (saturation) | Saturation probe before the pilot run; result recorded in BUILD_LOG (machine-checked) |
| n=2 over-interpretation | Stated as the FIRST limitation everywhere results appear; numbers describe these tasks, not "desk work" |
| Free-tier rate limits | Retry/backoff + per-run on-disk cache; 48+48 calls spread across 4 providers |
| Looks like AI-generated boilerplate | BUILD_LOG.md with dated decisions; external audit committed; opinionated writeup; single source of truth per doc |

## Release
GitHub repo (MIT) + GitHub Pages dashboard + report; announced via findings-first LinkedIn/X post.
