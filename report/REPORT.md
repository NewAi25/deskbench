# DeskBench Pilot — Report

> Every number in this report is computed from files under `results/` by
> `deskbench analyze` — no hand-entered figures. The evidence chain (raw
> outputs, judge scores, human grades) is committed alongside it.

## What this is

A deliberately small pilot of a benchmark for messy real-world office work.
Every task ships as a **twin pair** — a *messy* original (superseded
instructions, scheduling clashes, duplicated rows, format noise) and a *clean*
twin with a **byte-identical prompt** and the noise stripped — so the
difference between a model's scores isolates what the mess itself costs.
**Matrix: 2 twin pairs × 4 free models × 3 runs = 48 completions**, every one
graded by a held-out LLM judge **and** by a human (100% coverage, blind to
judge scores). Total API spend: $0.

- Method details: [docs/methodology.md](../docs/methodology.md) (twin design,
  mess-penalty formula, silent-failure definition, calibration protocol).
- Interactive results + every raw output: [the dashboard](https://newai25.github.io/deskbench/site/).
- Chain of evidence: `results/raw/` → `results/scores/` + `results/human/` →
  `results/summary.json` → this report. No number here is hand-entered.

## Method in six lines

1. Tasks authored with **reference answers written before any model ran**;
   rubrics have weighted criteria with concrete 1/3/5 anchors + auto-fail
   conditions (fabrication, silent overwriting of ambiguous data).
2. Rubric criteria are split **CORE** (the underlying work; identical weights
   across the twin pair) vs **MESS** (handling the injected noise; messy only).
3. Runner executes 2×2×4×3 with vendor-default sampling; errors are recorded,
   not discarded; every record content-hash-pinned to its task version.
4. Held-out judge (`nemotron-3-ultra`, family-independent of all four
   leaderboard models) scores each output against the anchors, returning
   enforced JSON with per-criterion rationales.
5. The maintainer human-grades **all 48 outputs blind** and tags every wrong
   or incomplete answer **silent** (never flagged the specific problem) or
   **flagged**.
6. The analyzer computes: leaderboard, mess penalty (core criteria only,
   relative core weights, sign = clean − messy), silent-failure rate (human
   tags only), judge–human agreement, and run variance.

## Results

### Leaderboard (mean weighted total, 0–5; auto-fail forces a run to 0)

| Model | Judge overall | Judge messy | Judge clean | Human overall | Human messy | Human clean | Auto-fails (judge / human, of 12) |
|---|---|---|---|---|---|---|---|
| glm-4.7-flash | 2.795 | 2.525 | 3.065 | 3.254 | 2.850 | 3.658 | 1 / 1 |
| gpt-oss-20b-free | 2.722 | 3.008 | 2.436 | 2.839 | 2.883 | 2.794 | 2 / 1 |
| gemini-flash | 2.519 | 3.083 | 1.955 | 2.303 | 2.242 | 2.364 | 4 / 6 |
| llama-3.3-70b | 1.956 | 1.458 | 2.454 | 2.415 | 2.408 | 2.421 | 3 / 2 |

n = 12 runs per model per grader (per-run values: `results/tables/runs.csv`).
Judge and human agree on first place (glm-4.7-flash) but disagree on last:
the judge ranks llama-3.3-70b last, the human ranks gemini-flash last —
driven by auto-fail counts (gemini: 6 human auto-fails of 12 runs).

### Mess penalty (core criteria only; positive = mess degraded the model)

Per model (mean over the two twin pairs), computed independently from judge
and human scores:

| Model | Judge | Human |
|---|---|---|
| llama-3.3-70b | +0.716 | +0.427 |
| gpt-oss-20b-free | +0.307 | +0.306 |
| glm-4.7-flash | +0.111 | +0.139 |
| gemini-flash | −0.106 | +0.131 |

Per twin pair (`results/tables/mess_penalty_per_pair.csv`):

| Model | T01 pair (judge / human) | T02 pair (judge / human) |
|---|---|---|
| gemini-flash | −0.545 / −0.000 | +0.333 / +0.262 |
| glm-4.7-flash | −0.848 / −0.485 | +1.071 / +0.762 |
| gpt-oss-20b-free | −0.242 / +0.303 | +0.857 / +0.310 |
| llama-3.3-70b | +0.576 / +0.212 | +0.857 / +0.643 |

On the reconciliation pair (T02) **every model pays a positive mess penalty
under both graders**. On the inbox pair (T01) two models score *better* messy
than clean under both graders (negative penalty) — see Findings.

### Silent-failure rate (human tags; silent / (silent + flagged), na excluded)

| Model | Silent | Flagged | n/a (nothing wrong) | Rate |
|---|---|---|---|---|
| gemini-flash | 6 | 0 | 6 | 1.000 |
| glm-4.7-flash | 11 | 0 | 1 | 1.000 |
| gpt-oss-20b-free | 12 | 0 | 0 | 1.000 |
| llama-3.3-70b | 8 | 4 | 0 | 0.667 |

Across all models: 37 of 41 wrong/incomplete outputs (90%) never flagged the
specific thing that was wrong. Only llama-3.3-70b ever flagged.

### Judge–human agreement (n = 48 pairs, 100% human coverage)

- **Weighted totals:** Pearson r = **0.694**, MAE = **0.769** (on a 0–5 scale).
- **Auto-fail:** exact-match rate **0.875** (42/48); the six mismatches are the
  six largest total disagreements (see below).
- **Per criterion** (`results/tables/agreement_per_criterion.csv`):

| Criterion | n | r | MAE |
|---|---|---|---|
| correct-reconciled-total | 24 | 0.916 | 0.292 |
| catches-superseded-instruction | 12 | 0.897 | 0.500 |
| finds-duplicate | 24 | 0.890 | 0.292 |
| correct-prioritization | 24 | 0.737 | 0.500 |
| catches-scheduling-conflict | 12 | 0.686 | 0.667 |
| identifies-real-vs-cosmetic | 12 | 0.651 | 0.917 |
| reply-quality | 24 | 0.576 | 1.083 |
| discrepancy-list-quality | 24 | 0.511 | 0.708 |
| surfaces-not-silently-resolves | 24 | 0.473 | 1.000 |
| flags-ambiguity-not-guesses | 24 | 0.289 | 1.125 |

- **Ten largest disagreements** (`results/tables/disagreements.csv`): the top
  six are all auto-fail direction mismatches — three where the judge
  auto-failed a T01/T01c output the human scored ~3.3–3.7, and three where
  the human auto-failed a T02 output (silent Everest overwrite) the judge
  scored 2.3–2.9.

### Run-to-run variance

Across-run sample std dev of the weighted total ranges from 0.0 to 2.36
per (model, task) cell (`results/tables/variance.csv`); 9 of the 16
model×task cells exceed 1.0 under at least one grader. With n = 3 runs,
single-run readings of these tasks would be unreliable for most cells.

---

## Findings

- The mess penalty exists and is measurable, but it is
  task-shaped, not universal: every model pays it on the data-reconciliation
  pair (T02, up to +1.07), while on the inbox pair (T01) two models actually
  scored *better* on the messy variant under both graders. One reading: T01's
  traps (superseded deadline, calendar clash) give strong models easy
  opportunities to demonstrate exactly the behaviors the rubric rewards,
  while the clean twin leaves less to show off; the byte-identical prompt
  also asks for a conflicts section that is (correctly) near-empty on clean
  materials, which some models handled awkwardly.
- Silent failure is the norm, not the exception: 90% of all
  wrong/incomplete answers (37/41) never flagged the specific problem, and
  three of four models did not flag a single one. The behavior the rubrics
  reward most — saying "this is ambiguous, confirm before acting" — is
  almost entirely absent from free-tier model output.
- The judge is trustworthy on verifiable criteria and weak on
  judgment criteria: r ≈ 0.89–0.92 where the rubric checks a computable fact
  (reconciled total, duplicate row, superseded instruction) but r ≈ 0.29–0.58
  on "did it flag ambiguity / surface rather than silently resolve /
  reply-quality". Judge-only evaluation of judgment-heavy office work would
  be substantially less reliable than these headline scores suggest.
- The biggest judge–human gaps are auto-fail direction calls, not
  score calibration: 6 of 48 records disagree on auto-fail and they are the
  6 largest total gaps. The human read three T02 "confident Everest fixes"
  as auto-fail fabrication where the judge scored them ~2.5; the judge
  auto-failed three T01 outputs the human found merely mediocre.
- Leaderboard means at n = 3 runs hide large run-to-run variance
  (std dev up to 2.36); per-cell whiskers on the dashboard matter more than
  the ranking.

## What these results do NOT show

- **First, always: n = 2 tasks.** Two twin pairs cannot characterize
  "office work". These numbers describe *these two tasks* — an inbox triage
  and a ledger reconciliation — and nothing broader. Every claim above is a
  claim about this suite.
- Free-tier models only. Nothing here estimates frontier-model
  capability; the pipeline accepts any OpenAI-compatible endpoint, but that
  run has not happened.
- One human grader, with a disclosed calibration protocol but no
  second rater — there is no inter-rater reliability number, so "human" here
  means "one careful human", not "human consensus".
- Judge-only numbers inherit the agreement ceiling above
  (r = 0.694 overall, far lower on judgment criteria); the leaderboard is
  reported from both graders for exactly that reason.
- The mess penalty's cross-variant comparability rests on the
  anchor-parity curation judgment disclosed in methodology §3 — reviewed,
  but a judgment, not a theorem.
- Static tasks cannot prove contamination resistance; "authored
  fresh" is a claim about the past. The v2 answer is the generator design
  below.
- Silent-failure denominators are small (4–12 wrong answers per
  model); the 1.000 rates are real counts, not precise estimates.

## Next steps — the roadmap centerpiece

The pilot proves the grading method (twins, CORE/MESS split, validated
judge). The scaling path is **[ADR-003 — benchmark as a function]
(../docs/adr/ADR-003-benchmark-as-a-function.md)**: each task becomes a
seeded template whose parameter draws *change the correct answer*, with the
reference computed from the drawn parameters. That yields provable
contamination resistance (a fresh draw defeats memorization), clean twins
for free (`noise=off` is a parameter), and real statistical power (n draws
per template) — with the honestly-stated risk that shallow parameter
diversity would make it a gimmick, and the mitigations ADR-003 commits to
(structural parameters, cross-draw diversity audits, effective-n reporting,
human-graded samples of generated references). T02's twin was already
produced by a prototype generator (`scripts/gen_t02.py`) — the existence
proof that the pilot's curation judgments can be encoded as parameter axes.

Nearer-term: a second human rater on a sample (inter-rater number), an
independent-provider judge (the OpenRouter free-pool contention documented in
BUILD_LOG), and more twin pairs across the remaining categories.

## Reproduce

```
pip install -e ".[dev]"
deskbench analyze     # results/ -> summary.json + tables (no keys needed)
deskbench render      # -> site/index.html
pytest                # 120 tests, incl. hand-computed fixtures for every formula
```

Raw outputs, judge scores, human grades, and the grading sheet are all
committed under `results/` — every number above traces to a file a reviewer
can open.
