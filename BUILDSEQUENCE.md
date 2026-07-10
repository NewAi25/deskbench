# DeskBench — Build Sequence & Status

<!-- STATUS:BEGIN — this table is auto-updated by .github/workflows/build-status.yml on every push. Do not edit by hand. -->

| Step | What | Module(s) | Definition of Done (machine-checked) | Status |
|------|------|-----------|--------------------------------------|--------|
| 0 | Repo & scaffolding | — | CI workflow green; `pyproject.toml`, `README.md`, `.env.example` exist | ⬜ pending |
| 1 | Schemas | `schemas.py` | `tests/test_schemas.py` passes; all 4 contracts defined | ⬜ pending |
| 2 | Model registry | `registry.py` | `tests/test_registry.py` passes; `config/models.yaml` has ≥4 models | ⬜ pending |
| 3 | Pilot tasks + rubrics | tasks T01–T02 | 2 task dirs schema-validate (task.yaml, rubric.yaml, reference.md, artifacts/); saturation check logged in BUILD_LOG | ⬜ pending |
| 4 | Runner | `runner.py` | `tests/test_runner.py` passes; ≥1 raw result JSON committed as fixture | ⬜ pending |
| 5 | Grader | `grader.py` | `tests/test_grader.py` passes; ≥1 score JSON fixture validates | ⬜ pending |
| 6 | Full task suite | tasks T03–T12 | 12 task dirs schema-validate; all 5 categories covered | ⬜ pending |
| 7 | Judge validation | `analyzer.py` (agreement) | `results/human/` has ≥30% sample; agreement metrics in `results/summary.json` | ⬜ pending |
| 8 | Full run & analysis | `analyzer.py` | `results/summary.json` complete: leaderboard, variance, failure taxonomy | ⬜ pending |
| 9 | Visualizer | `visualize.py` | `site/index.html` exists and embeds summary data; renders all 8 sections | ⬜ pending |
| 10 | Writeup & ship | `cli.py` polish, report | `report/REPORT.md` has "What these results do NOT show" section; README has dashboard screenshot | ⬜ pending |

<!-- STATUS:END -->

Legend: ⬜ pending · 🟨 in progress · ✅ done

## How auto-update works

A GitHub Action (`.github/workflows/build-status.yml`) runs on every push to `main`:

1. Runs `python scripts/build_status.py`, which checks each step's **machine-checkable DoD** above — file existence, schema validation of task dirs, and pytest results per test module. No commit-message parsing, no honor system: a step is ✅ only when its artifacts actually exist and its tests actually pass.
2. A step whose predecessor is ✅ but whose own checks partially pass is marked 🟨 in progress.
3. If any status changed, the script rewrites the table between the `STATUS:BEGIN/END` markers and the workflow commits it back with message `chore: update build status [skip ci]`.

Why this design (will become ADR-003):
- **Push = status update.** Exactly what you asked: finish a step, `git push`, table flips to ✅ on its own.
- **Statuses can't lie.** The table is derived from the repo's actual state, so it doubles as a public integrity signal — a reviewer can verify any ✅ by running the same script.
- **`[skip ci]` + marker comments** prevent workflow loops and merge conflicts.

## Build rules

1. Steps complete in order; no starting step N+1 before step N is ✅ (the script flags out-of-order completions as ⚠️).
2. Every ✅ flip must be accompanied by a dated `BUILD_LOG.md` entry in the same or previous commit.
3. The status script itself gets a test (`tests/test_build_status.py`) — the tool that certifies the work must itself be certified.
