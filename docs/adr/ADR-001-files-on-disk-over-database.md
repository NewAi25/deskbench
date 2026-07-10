# ADR-001 — Files on disk over a database

- **Status:** Accepted
- **Date:** 2026-07-11
- **Deciders:** DeskBench author
- **Context source:** BUILD_PLAN.md §1 & §4, ARCHITECTURE_REVIEW.md

## Context

The pipeline produces a small, bounded set of records: 12 tasks × 4 models ×
3–5 runs ≈ 200 raw results, plus a matching number of scores and a stratified
human-grade sample. Every box (runner, grader, analyzer, visualizer)
consumes the previous box's output and produces the next. The audience —
evals researchers and hiring reviewers — must be able to audit any number on
the dashboard back to the exact model output that produced it.

The obvious alternatives for the store are a relational database
(SQLite/Postgres) or an object/document store. The plan chooses plain files on
disk: YAML for hand-authored inputs (`task.yaml`, `rubric.yaml`,
`models.yaml`), JSON for machine-produced records (`results/raw/*.json`,
`results/scores/*.json`), content-addressed by `{task_id}__{model_id}__run{n}`.

## Decision

Persist every contract as a file on disk. No database. Records are validated on
read/write against the pydantic models in `deskbench/schemas.py`, and version
integrity is enforced with content hashes (see ADR-002 / fix #2), not with
foreign keys.

## Rationale

1. **The chain of evidence must be visible.** A reviewer can `cat` a raw result,
   see the judge's rationale in the score file next to it, and trace it to the
   `summary.json` number — no query language, no schema migration, no server. A
   database hides exactly the chain of evidence that files expose.

2. **The data volume is trivial and non-concurrent.** ~200 records, one writer
   (the CLI, run by one person). None of a database's strengths — concurrent
   writers, indexed queries over millions of rows, transactional integrity under
   contention — apply. There is no query a plain directory walk cannot answer at
   this scale.

3. **Re-runnability in isolation is the key invariant.** Delete
   `results/scores/` and re-grade without re-querying any model; delete
   `site/index.html` and re-render. Files make each stage independently
   reproducible and diffable in git. A database couples the stages through a
   shared mutable store.

4. **Longevity.** A directory of YAML and JSON is readable with no tooling in
   five years. A database file needs its engine, its version, its schema.

5. **Diff-based review.** Task and rubric edits show up as line diffs a human
   can review in a pull request — central to a benchmark whose whole value is
   curation and grading judgment.

## Consequences

- **Easier:** auditing, re-running one stage, adding a task (drop a folder) or a
  model (one config line), reviewing changes as diffs, trusting the results.
- **Harder:** ad-hoc cross-cutting queries ("all runs where the judge scored ≥4
  but a human scored ≤2") require a small analyzer pass rather than a SQL
  `WHERE`. At this scale that pass is a few lines of Python over a directory
  glob — acceptable, and it lives in `analyzer.py`.
- **Integrity without foreign keys:** because there is no referential integrity
  from a database, every raw result and score embeds the content hashes of the
  task and rubric it was produced against (fix #2). The analyzer refuses to
  aggregate records whose hashes do not match the current suite. This replaces
  DB constraints with content-addressing, which is stronger for reproducibility:
  it detects not just missing references but *changed* ones.

## Revisit when

- Record count exceeds ~50 tasks × many models such that directory walks become
  slow (unlikely within the project's scope), or
- more than one contributor needs to write results concurrently, or
- the analysis genuinely needs relational queries across large joined tables.

At any of those, a read-through cache into SQLite (files remaining the source of
truth) is the first step to consider — not a wholesale move to a database.
