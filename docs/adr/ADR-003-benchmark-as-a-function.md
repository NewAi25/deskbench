# ADR-003: Benchmark as a function, not a list (v2 roadmap)

**Status:** Proposed — designed for v2, deliberately NOT built in the pilot
(MVP pivot, 2026-07-11; recorded as the roadmap centerpiece per the 2026-07-16
docs-alignment audit).

## Context

The pilot ships hand-authored task *instances*: fixed artifacts, a hand-written
reference, a hand-curated clean twin. That is the right way to prove the
grading method (twin design, CORE/MESS rubrics, human-validated judge), but it
has three structural ceilings:

1. **Contamination is unfalsifiable.** A released static task is, from that
   moment, potentially in some future training set. "Authored fresh" is a
   claim about the past, not a defense going forward.
2. **n = 1 per task.** One instance per task means task-level results ride on
   authoring luck; there is no way to separate "this model can't reconcile
   ledgers" from "this model tripped on this ledger."
3. **Twins are expensive.** Each clean twin is a second hand-authoring +
   curation pass, with anchor-parity review to boot.

## Decision (the v2 design)

Make each task a **parameterized template — a function, not a list**:

```
generate(template, seed) -> (artifacts, correct_answer, rubric_bindings)
```

- **Seeded parameter draws change the correct answer.** For an inbox-triage
  template: which instruction is superseded, which deadline is truly binding,
  which meeting clashes. For a reconciliation template: which row is
  duplicated, which value drops a zero, what the true total is. Two draws are
  two different problems with two different right answers — not reskins of one.
- **References are computed, not written.** The generator knows the drawn
  parameters, so it *derives* the reference answer (the binding deadline IS
  parameter `d3`; the correct total IS `sum(amounts) `). The pilot's
  reference-before-model discipline becomes reference-by-construction.
- **The core/noise split becomes a parameter axis.** Every template separates
  **core parameters** (change the answer: amounts, deadlines, which trap is
  armed) from **noise parameters** (change only the surface: name variants,
  date formats, currency formatting, filler emails). `noise=off` IS the clean
  twin — the pilot's hand-curated twin design, produced mechanically, with the
  CORE/MESS rubric split binding to the same axes.
- **Rubric anchors bind to parameters.** Anchors reference the drawn values
  ("names the exact clash: {p.clash_a} vs {p.clash_b}"), so anchor strictness
  is parity-by-construction across variants — the pilot's curation caveat
  (methodology.md §3) becomes a generated invariant.

### What this buys, concretely

- **A contamination claim you can prove:** publish the template AND the graded
  instances; a challenged result is re-run on a fresh seed. Memorizing released
  instances doesn't move the answer of the next draw.
- **Statistical power:** n = 30 draws per template turns "tripped on this
  ledger" and "can't reconcile ledgers" into distinguishable hypotheses.
- **Twins for free**, at every difficulty level the noise axes can express.

## The honest risk: shallow parameter diversity makes it a gimmick

If a template's parameters only rename customers and shuffle numbers, 50 draws
are 50 reskins of one problem — a generator-shaped benchmark that measures one
task while claiming n=50. That failure mode is *worse* than the static suite,
because it launders a small benchmark into big-benchmark statistics.

Mitigations the v2 build must carry:

1. **Structural parameters, not just surface ones.** Draws must vary which
   *kind* of trap is armed (supersession vs clash vs neither vs both), not just
   the trap's fillers. If every draw has the same skeleton, say so and count it
   as one task.
2. **Diversity audit before trusting n.** Measure cross-draw agreement per
   model (if a model's scores across draws are near-constant, the draws are one
   problem) and report effective-n alongside raw n.
3. **Human-grade a sample of every template's draws** — generated references
   can encode a generator bug as "truth"; the pilot's judge-validation
   discipline applies to the generator too.
4. **The pilot is the existence proof.** T01/T02's hand curation (which traps,
   which noise, what stays core) is exactly the judgment the parameter axes
   must encode. v2 templates are written by generalizing audited pilot tasks,
   never invented cold.

## Alternatives considered

- **Scale the static suite to 12 hand-authored tasks** (the original plan):
  linear authoring cost, unfalsifiable contamination story, n=1 per task
  forever. Rejected as the *end state*; it remains the fallback if template
  diversity proves shallow.
- **Perturb static tasks post-hoc** (paraphrase, rename, reformat): cheap, but
  changes only surface — the answer stays put, so contamination resistance is
  cosmetic. Rejected.
- **LLM-generated tasks with LLM-written references:** maximally cheap,
  minimally trustworthy — the reference inherits the generator model's blind
  spots and the contamination story becomes circular. Rejected for v2; a human
  owns every template.

## Consequences

- v2's unit of contribution shifts from "a task" to "a template + its
  diversity evidence" — authoring gets harder per unit, then free per instance.
- The pilot's schemas already carry the seams: `variant` and `twin_of` on
  Task, `kind` on criteria, content-hash versioning per instance. A generated
  instance is just a task dir the generator wrote — the pipeline (runner,
  grader, analyzer, dashboard) does not change.
- Until v2 lands, every DeskBench number is read against n=2 hand-authored
  tasks, and the report says so first.
