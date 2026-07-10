# DeskBench — PRD (one page)

## Problem
Public AI benchmarks over-index on exams and code. Almost none measure the messy, ambiguous, judgment-heavy tasks that make up real office work — and those that try rarely publish validated grading methods. Hiring managers, researchers, and practitioners have no grounded way to answer "can this model actually do desk work?"

## Goal
A small, open, rigorously graded benchmark (12 tasks, 5 categories) that measures how well language models handle realistic office work, with published rubrics, a validated LLM judge, and a fully reproducible $0 pipeline.

## Users
1. **Primary:** AI-evals researchers and practitioners who want a grounded read on practical model capability.
2. **Secondary:** hiring reviewers (e.g., Epoch AI) assessing the author's evaluation-research ability — the repo is itself a work sample.
3. **Tertiary:** anyone adding a model or task (contribution path documented).

## Success criteria (v1)
- 12 tasks with artifacts, reference answers, and anchored rubrics — all schema-validated in CI.
- 4 models evaluated, ≥3 runs each; judge–human agreement measured on ≥30% sample and reported, whatever the number.
- Score spread across models/tasks (no saturation): task suite discriminates.
- One-command pipeline (`deskbench all`); adding a model = one config line.
- Public dashboard + written report incl. "what these results do NOT show."
- Total API spend: $0.

## Non-goals (v1)
- Scale (no 100-task suite; 12 excellent > 50 mediocre).
- Frontier-model coverage (free-tier models only; harness accepts any OpenAI-compatible endpoint later).
- Complex multi-step agent environments (exactly 2 tasks use tools; rest self-contained).
- Localized/India-flavored task slice (deferred to v1.1).
- Leaderboard-as-a-service, submissions, or hosting infrastructure.

## Key risks & mitigations
| Risk | Mitigation |
|---|---|
| LLM judge unreliable | Human-grade 30% sample, report agreement; iterate rubrics with before/after numbers |
| Judge self-preference | Judge model excluded from leaderboard; self-preference check if unavoidable |
| Tasks too easy (saturation) | Pilot difficulty check at Step 3 before scaling |
| Free-tier rate limits | Retry/backoff + on-disk cache; run spread over 2 days across 4 providers |
| Looks like AI-generated boilerplate | BUILD_LOG.md with dated decisions; opinionated writeup; single source of truth per doc |

## Release
GitHub repo (MIT) + GitHub Pages dashboard + report; announced via findings-first LinkedIn/X post.
