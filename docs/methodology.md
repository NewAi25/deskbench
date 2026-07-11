# Methodology (DeskBench Pilot)

The scientific heart of the pilot: how outputs are graded, how the mess penalty
and silent-failure rate are defined, how the judge is validated, and what the
results do **not** support. Every claim in the report is computed from files in
`results/`; nothing here is hand-entered.

## 1. Grading philosophy

- **Grade against the rubric anchors, not similarity to the reference.** The
  reference is one competent answer, given to the judge as context only. Valid
  alternative approaches must score well. (Judge prompt + enforcement:
  [ADR-002](adr/ADR-002-judge-prompt-and-independence.md).)
- **Judge independence.** The judge (Qwen2.5-72B) is held out of the leaderboard
  and may never grade its own family; the registry enforces this mechanically.
- **Structured, enforced output.** The judge returns per-criterion 1-5 scores
  with anchor-citing rationales as strict JSON; malformed replies are
  reject-and-retried, never patched into a fabricated score.

## 2. Reference-before-model discipline

Every `reference.md` was written **before any model was run** on the task. This
forces us to prove the task is solvable and to decide what "good" means before
any model output can anchor judgement, and it documents that the tasks are
freshly authored (contamination note: synthetic tasks authored fresh cannot be
in a training set).

## 3. The twin design and the MESS PENALTY

Each task ships as a **twin pair**: the *messy* original (realistic noise) and a
*clean* twin (the same underlying problem, noise stripped). Comparing a model's
performance across the pair isolates how much the mess — not the core task —
costs it.

### Core vs. noise (a per-task judgement)

- **CORE** facts define the problem and determine the correct answer. **NOISE**
  is mess overlaying them. The clean twin keeps the same core facts and strips
  only noise.
- **For error-finding tasks the errors ARE core.** `T02c` keeps *both* genuine
  discrepancies (the duplicated row and the dropped-zero) and removes only
  format / name / date noise — the model must still find the real errors.
- **For `T01`, the traps ARE the mess.** `T01c` keeps the prioritization problem
  with the *same emails* and the correct final deadline, but removes the
  superseded-instruction trap and the calendar clash. So `T01c` measures
  baseline triage competence, and the penalty measures the cost of the traps.
- **This asymmetry is deliberate:** what counts as core vs. noise is a per-task
  curation judgement, not a mechanical rule, and it is recorded in each task's
  `author_notes` and reviewed as such.

### CORE / MESS rubric split

Each rubric criterion carries a `kind`: **core** (grades the underlying work;
present in both twins) or **mess** (grades handling of the injected noise;
messy rubric only). The **relative** core weights are identical across a twin
pair, so the two variants grade the same underlying work the same way.

### Mess-penalty formula (confirmed)

For a twin pair and a model, the mess penalty is the **core-weight-weighted mean
of the per-criterion score deltas**, using the shared **relative** core weights:

```
mess_penalty(model) = Σ_core  w_rel(c) · ( score_clean(c) − score_messy(c) )
                      over core criteria c,   Σ_core w_rel(c) = 1
```

- **Sign convention: clean − messy. A positive penalty means the mess degraded
  the model** (it scored lower on the same core work once noise was present).
- It is computed from **per-criterion scores**, **never** as a difference of the
  two variants' `weighted_total`s (those aren't comparable across a differing
  criterion set).

### Cross-variant comparability caveat

Comparing scores across the twin rests on the anchors being **equally strict in
both variants** — a core criterion's score-5 anchor must demand the same quality
of work whether or not noise is present. Anchor wording may adapt per variant
(the clean twin references no superseded note, for instance), so equal strictness
is a **curation judgement**, reviewed with that standard in mind.

## 4. SILENT-FAILURE RATE

A wrong or incomplete answer is counted as **FLAGGED** only if the output
**explicitly signals uncertainty or requests verification on the specific point
that is wrong**. Generic hedging ("please double-check my work") does **not**
count as flagging. Everything else wrong is a **SILENT** failure.

The silent-vs-flagged tag is **assigned by a human during grading, never by the
judge**, in v1. (Judge-assigned failure tagging would be a second judged task
needing its own validation — deferred to the roadmap.)

## 5. Judge validation

At pilot scale (2 tasks × 2 variants × 4 models × 3 runs = 48 completions) the
outputs are **human-graded at 100%**, blind to the judge's scores. Judge–human
agreement is reported as correlation and mean absolute difference per criterion —
**whatever the number is**. If agreement is weak, the rubric/judge prompt is
revised and re-run, and the before/after numbers are kept.

## 6. What this does not show (pointer)

The pilot is deliberately small. The **first** limitation is **n = 2 tasks** —
far too few to characterize a model's office-work ability; the numbers describe
these tasks, not "desk work" in general. Only free-tier models are tested. The
full limitations section and the generator roadmap live in the report.
