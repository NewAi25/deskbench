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
