# DeskBench — Build Sequence & Status

<!-- STATUS:BEGIN — this table is auto-updated by .github/workflows/build-status.yml on every push. Do not edit by hand. -->

| Step | What | Module(s) | Definition of Done (machine-checked) | Status |
|------|------|-----------|--------------------------------------|--------|
| 0 | Repo & scaffolding | — | CI workflow green; `pyproject.toml`, `README.md`, `.env.example` exist | ✅ done |
| 1 | Schemas | `schemas.py` | `tests/test_schemas.py` passes; all 4 contracts defined | ✅ done |
| 2 | Model registry | `registry.py` | `tests/test_registry.py` passes; `config/models.yaml` has ≥4 models | ✅ done |
| 3 | Pilot tasks + rubrics | tasks T01–T02 | 2 task dirs schema-validate (task.yaml, rubric.yaml, reference.md, artifacts/); a recorded saturation result in BUILD_LOG (a line starting `SATURATION RESULT`, bold/parenthetical allowed) | ✅ done |
| 4 | Runner | `runner.py` | `tests/test_runner.py` passes; ≥1 raw result JSON committed as fixture | ✅ done |
| 5 | Grader | `grader.py` | `tests/test_grader.py` passes; ≥1 score JSON fixture validates | ✅ done |
| 6 | Clean twins (MVP) | tasks T01c–T02c | 4 task dirs schema-validate (2 twin pairs); twin invariants pass (`tests/test_tasks.py`: byte-identical prompts, shared core criteria at identical weights) | ✅ done |
| 7 | Pilot run + judge grading | `runner.py`, `grader.py` | 48 raw results (2 tasks × 2 variants × 4 models × 3 runs) and 48 judge scores present under `results/` | ✅ done |
| 8 | Human validation + analysis | `analyzer.py`, `results/human/` | 100% human grading sheet ingested; `results/summary.json` has leaderboard, mess_penalty, silent_failure, agreement, variance | ✅ done |
| 9 | Pilot dashboard | `visualize.py` | `site/index.html` embeds summary data; renders the four pilot charts + run inspector | ✅ done |
| 10 | Pilot report & ship | `report/REPORT.md` | REPORT.md has "What these results do NOT show" (n=2 tasks stated first); README reframed to pilot; no hand-entered numbers | ⬜ pending |

<!-- STATUS:END -->

Legend: ⬜ pending · 🟨 in progress · ✅ done

> **MVP descope (2026-07-11).** Steps 6–10 were re-scoped from the original
> 12-task plan to the "DeskBench Pilot" MVP: 2 tasks × 2 variants (messy +
> clean twin) × 4 models × 3 runs, judge-graded with 100% human validation,
> reporting leaderboard, mess penalty, silent-failure rate, and judge–human
> agreement. The generator vision is the v2 roadmap (see
> [ADR-003](docs/adr/ADR-003-benchmark-as-a-function.md) and REPORT.md next
> steps). Original step definitions live in git history.

## How auto-update works

A GitHub Action (`.github/workflows/build-status.yml`) runs on every push to `main`:

1. Runs `python scripts/build_status.py`, which checks each step's **machine-checkable DoD** above — file existence, schema validation of task dirs, and pytest results per test module. No commit-message parsing, no honor system: a step is ✅ only when its artifacts actually exist and its tests actually pass.
2. A step whose predecessor is ✅ but whose own checks partially pass is marked 🟨 in progress.
3. If any status changed, the script rewrites the table between the `STATUS:BEGIN/END` markers and the workflow commits it back with message `chore: update build status [skip ci]`.

Why this design:
- **Push = status update.** Exactly what you asked: finish a step, `git push`, table flips to ✅ on its own.
- **Statuses can't lie.** The table is derived from the repo's actual state, so it doubles as a public integrity signal — a reviewer can verify any ✅ by running the same script.
- **`[skip ci]` + marker comments** prevent workflow loops and merge conflicts.

## Build rules

1. Steps complete in order; no starting step N+1 before step N is ✅. (Tightening a step's DoD may honestly *regress* an already-✅ step — e.g. Step 3 regressed to 🟨 on 2026-07-16 when its predicate was strengthened to require a recorded saturation result, per the audit's F3. Later ✅ steps are not unwound by such a regression; the table reports current truth, not history.)
2. Every ✅ flip must be accompanied by a dated `BUILD_LOG.md` entry in the same or previous commit.
3. The status script itself gets a test (`tests/test_build_status.py`) — the tool that certifies the work must itself be certified.
