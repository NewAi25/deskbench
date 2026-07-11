# Reference answer — T02c Spreadsheet Reconciliation (clean twin)

*Written before any model was run. Grade against the rubric anchors, not against
exact wording. The numeric conclusions, however, are determinate.*

## 1. Correct reconciled total

**43,650** (five distinct deals), assuming the CRM's Everest figure of 15,000 is
the correct one and that the duplicated finance row is removed.

- CRM export sums to **43,650** and contains five clean, distinct deals.
- Finance ledger sums to **38,550**, which is 5,100 lower — the net of two
  offsetting problems (see below).

Because the one genuine disagreement (Everest) cannot be settled from the files
alone, the honest answer states the assumption: *if* Everest is 15,000 (CRM), the
reconciled total is **43,650**; *if* it were truly 1,500 (finance), it would be
30,150. The 1,500 is almost certainly a dropped zero and should be confirmed
with the deal owner before close.

## 2. Line-by-line reconciliation

| Deal | CRM | Finance | Classification |
|------|-----|---------|----------------|
| Acme (1001) | Acme Corp, 12000.00 | Acme Corp, 12000.00 | **Identical** — no difference. |
| Bluecrest (1002) | Bluecrest Ltd, 8400.00 | Bluecrest Ltd, 8400.00 — **appears twice** | **Genuine (duplicate)** — the finance ledger double-counts row 1002 (+8,400). Remove one row. |
| Cirrus (1003) | Cirrus, 5250.00 | Cirrus, 5250.00 | **Identical** — no difference. |
| Delta (1004) | Delta Systems, 3000.00 | Delta Systems, 3000.00 | **Identical** — no difference. |
| Everest (1005) | Everest Retail, 15000.00 | Everest Retail, 1500.00 | **Genuine data error** — the amounts truly disagree (15,000 vs 1,500). Looks like a dropped zero in finance. This is the one real error to fix. |

Reconciliation of the 5,100 gap: finance is inflated +8,400 by the Bluecrest
duplicate and deflated −13,500 by the Everest error → net −5,100, exactly the
observed difference (43,650 − 38,550).

## 3. The real error vs. the cosmetic noise

- **The single genuine data error is Everest (1005): 1,500 vs 15,000.** It
  should be corrected/confirmed with the deal owner (almost certainly 15,000).
- **The Bluecrest duplicate is a genuine ledger problem too** (a double-counted
  row), but it's a data-entry duplication, not a disagreement about a value —
  fix by removing the extra row.
- **There are NO cosmetic differences in these files.** Names, dates, and number
  formats agree everywhere; the only differences between the two exports are the
  two genuine problems above. The correct classification says exactly that,
  rather than manufacturing cosmetic findings to fill the category.

**Assumption stated:** the CRM's 15,000 for Everest is treated as correct
pending confirmation with the deal owner.
