# ADR-002 — Judge prompt design and judge-independence policy

- **Status:** Accepted
- **Date:** 2026-07-11
- **Deciders:** DeskBench author
- **Context source:** BUILD_PLAN.md §5 (Step 5), ARCHITECTURE_REVIEW.md fix #1

## Context

Box 4 (the grader) turns a model's free-text answer into a number by asking an
LLM **judge** to score it against the task's rubric. Two things decide whether
that number is trustworthy: *how the judge is prompted*, and *which model
judges*. This ADR records both.

## Decision 1 — Judge prompt design

The judge prompt (`grader.build_judge_prompt`) is built from the rubric, the
reference, and the candidate output, under these rules:

1. **Score against the anchors, not the reference.** The prompt states the
   reference is "one competent answer, provided for context only — NOT the
   grading target", and instructs the judge to score each criterion against its
   1/3/5 anchors. This is the single most important instruction: without it, an
   LLM judge collapses into a similarity-to-reference metric and penalizes valid
   alternative approaches. The reference is included (it helps calibrate) but
   explicitly demoted.
2. **Cite the anchor in every rationale.** The judge must say which anchor it
   matched. This is what makes rationales auditable ("cites the rubric anchors,
   not vibes" — the Step 5 DoD) and lets a human validator later check the judge
   against ground truth (Step 7).
3. **Structured output, mechanically enforced.** The judge must return a strict
   JSON object scoring *every* criterion, plus an `auto_fail` verdict.
   `parse_judge_response` validates it: unknown/missing/duplicate criteria, an
   out-of-range score, or an empty rationale are all rejected.
4. **Reject-and-retry, never fabricate.** A malformed reply is not patched or
   guessed — the judge is re-asked up to `max_attempts` (default 3). Persistent
   failure raises `GraderError`; the pipeline would rather have no score than an
   invented one.
5. **Auto-fail forces zero.** If the judge flags a rubric auto-fail condition
   (e.g. fabricated data), the weighted total is forced to 0.0 regardless of the
   per-criterion scores.

### Why enforce JSON rather than parse prose

Free-text judgements are unparseable at scale and hide disagreement. A strict
schema makes the judge commit to a number per criterion with a reason, which is
exactly what the analyzer and the human-agreement check (Step 7) consume. The
cost — occasional reject-and-retry — is cheap and observable.

## Decision 2 — Judge independence (fix #1)

**The judge is held out of the leaderboard and may never grade its own family.**

- `config/models.yaml` has a separate `judge:` entry; the registry **refuses to
  load** a config whose judge shares an `id` *or* a `litellm_model` with any
  leaderboard model. This is mechanical, not a convention — it can't regress
  silently.
- v1 judge: **Qwen2.5-72B-Instruct** (Alibaba), independent of all four
  leaderboard families (Google / Zhipu / Meta / DeepSeek), so it cannot
  self-prefer any leaderboard entry. Rationale in BUILD_LOG (Step 2).
- **If free tiers ever force overlap** (the only available strong judge shares a
  family with a leaderboard model), the policy is: run an explicit
  self-preference check — compare the judge's scores for its own family against a
  second independent judge — and report the gap alongside the leaderboard rather
  than hiding it. We do not silently accept a compromised judge.

### Why this matters

LLM judges empirically favor their own model family. Reporting a leaderboard
where the judge is also a contestant would be a methodological hole a reviewer
would (rightly) drill into. Independence + the mechanical guard closes it.

## Consequences

- **Easier:** trusting the scores; auditing any grade back to a cited anchor;
  swapping the judge (one config line, independence enforced).
- **Harder:** if every strong free model eventually shares a family with a
  leaderboard entry, we must do (and report) the self-preference check rather
  than pick a weaker independent judge — a deliberate cost.
- **Deferred:** failure-mode *taxonomy* tagging is not a judge task in v1 — it is
  human-assigned in Step 7 (fix #5), so `Score.failure_modes` is left empty here.
  Making the judge assign failure modes would be a second judged task needing its
  own validation; that's a v1.1 item.

## Revisit when

- The human-agreement check (Step 7) shows weak judge–human correlation → revise
  the prompt and/or anchors and re-measure, keeping the before/after numbers.
- Free-tier availability forces a same-family judge → trigger the
  self-preference protocol above.
