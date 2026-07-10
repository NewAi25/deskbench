# Adding a task

A DeskBench task is a folder under `tasks/`. Adding one is dropping in four
files — no code. CI schema-validates every task on push
(`tests/test_tasks.py`), so a malformed task fails the build.

## Anatomy

```
tasks/T03-my-task/
├── task.yaml       # id, category, difficulty, prompt, artifact list
├── artifacts/      # the messy inputs the model must work from
│   └── ...
├── reference.md    # a competent human answer — WRITTEN BEFORE ANY MODEL RUN
└── rubric.yaml     # weighted criteria with 1/3/5 anchors + auto_fail
```

The directory name must equal the task `id` (content-addressing invariant, e.g.
`T03-my-task`). Use the next free `T##` and a short slug.

## The discipline: reference before model

**Write `reference.md` before you run any model on the task.** This is a
methodological commitment, not a nicety: it forces you to prove the task is
solvable by a competent human and to decide what "good" means *before* any model
output can anchor your judgement. It also documents that the tasks are freshly
authored (contamination note — they can't be in a training set).

## Make artifacts realistically messy

Real office work is dirty. The pilot tasks (T01, T02) are the pattern:

- **Real-sounding names and specifics** — people, companies, timestamps,
  invoice ids. Not "Person A / Company B".
- **A buried contradiction or superseded instruction.** T01: the CEO's later
  note quietly voids her earlier "top priority" deadline. Grading rewards
  catching it.
- **Dirty data with both cosmetic noise and a real error.** T02: date/currency/
  name-format mismatches (cosmetic) plus one genuine transposed-digit error and
  a duplicated row. The task is to *separate* the real problem from the noise.
- **Something that should be flagged, not silently resolved.** The strongest
  discriminator is whether a model surfaces ambiguity or confidently papers over
  it.

Keep the numbers/facts internally consistent so the reference has a determinate
answer — verify the arithmetic (T02's totals were checked to the rupee/dollar).

## Writing the rubric

`rubric.yaml` is where the grading judgement lives — it's the real
differentiator, so spend the time here.

- **Criteria weights must sum to exactly 1.0** (enforced by the schema).
- **Every criterion needs anchors for scores 1, 3 and 5** — concrete
  descriptions of what each level looks like *for this task*. "What does
  silently dropping the constraint look like (1) vs. flagging it (5)?" A
  colleague should be able to grade a human answer using only the rubric.
- **`auto_fail`** lists conditions that void the answer regardless of criteria —
  typically fabricated data or an unacknowledged impossible action.
- Grade against the **anchors**, not similarity to the reference: valid
  alternative approaches must score well.

Example criterion:

```yaml
  - name: catches-superseded-instruction
    weight: 0.25
    description: Recognizes that the later note overrides the earlier deadline.
    anchors:
      1: "Treats the earlier deadline as still binding; misses the supersession."
      3: "Uses the later timeline but never notes that it overrode the earlier one."
      5: "Explicitly flags that the later note supersedes the earlier."
```

## Categories and difficulty

- `category`: one of `communication`, `data-wrangling`, `synthesis`,
  `planning`, `compliance` (the five fixed categories).
- `difficulty`: `easy` | `medium` | `hard`.
- `tools_allowed`: keep it `[]` for self-contained tasks. Only **two** of the
  twelve v1 tasks use tools (file reading + code exec); everything else inlines
  its artifacts into the prompt. Agent loops multiply failure modes — contain
  them.

## Validate before committing

```bash
pytest tests/test_tasks.py          # schema-validates every task dir
python -c "from deskbench import schemas; \
  print(schemas.hash_task_dir('tasks/T03-my-task'))"
```

## Saturation check (before scaling the suite)

Before growing past the pilots, run the saturation probe (needs keys):

```bash
python scripts/saturation_check.py
```

It runs two models on the pilot tasks and prints the score spread. If everything
scores ≥4/5 the tasks don't discriminate — add ambiguity, conflicting
constraints, and dirtier data until they do.
