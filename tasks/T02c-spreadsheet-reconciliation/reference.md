# Reference answer — T02c Spreadsheet Reconciliation (clean twin)

*Written before any model was run. Grade against the rubric anchors, not against
exact wording. The numeric conclusions, however, are determinate.*

The two files describe the same 27 Q1 deals (IDs 1001–1027). Names, transaction
ids, dates, and number formats agree everywhere, so the **only** differences
between the exports are the three genuine problems below — there is no cosmetic
noise to classify.

## 1. Correct reconciled total

**375,740** (27 distinct deals), assuming the CRM's Everest figure of 15,000 is
the correct one and that the duplicated finance row is removed.

- CRM export sums to **375,740** and contains 27 clean, distinct deals.
- Finance ledger sums to **370,640**, which is 5,100 lower — the net of two
  offsetting problems (see below).

Because the one genuine *amount* disagreement (Everest) cannot be settled from
the files alone, the honest answer states the assumption: *if* Everest is 15,000
(CRM), the reconciled total is **375,740**; *if* it were truly 1,500 (finance),
it would be **362,240**. The 1,500 is almost certainly a dropped zero and should
be confirmed with the deal owner before close.

## 2. The genuine discrepancies

| Deal | CRM | Finance | Classification |
|------|-----|---------|----------------|
| Bluecrest (1012) | Bluecrest Ltd, 8400.00, one row | Bluecrest Ltd, 8400.00 — **appears twice** (row 1012 listed again lower in the file, after Tidewater 1021) | **Genuine (duplicate)** — the ledger double-counts row 1012 (+8,400). Remove one row. |
| Everest (1019) | Everest Retail, 15000.00 | Everest Retail, 1500.00 | **Genuine data error** — the amounts truly disagree (15,000 vs 1,500), a dropped zero in finance (−13,500). This is the one *amount* error to correct. |
| Halcyon (1008) | Halcyon Travel, 2024-03-05 | Halcyon Travel, 2024-02-05 | **Genuine timing discrepancy** — the two systems disagree on the *close date* by a full month (March vs February), not on the amount (11,200 in both). It does **not** change the Q1 total, but it is a real data disagreement to flag. |

Reconciliation of the 5,100 gap: finance is inflated **+8,400** by the Bluecrest
duplicate and deflated **−13,500** by the Everest dropped zero → net **−5,100**,
exactly the observed difference (375,740 − 370,640). The Halcyon date mismatch
nets to zero (same amount both sides) and so does not enter the total.

## 3. The real error vs. the cosmetic noise

- **The single genuine *amount* error to correct is Everest (1019): 1,500 vs
  15,000** — almost certainly a dropped zero; confirm with the deal owner.
- **The Bluecrest duplicate is a genuine ledger problem too**, but it is a
  data-entry duplication, not a disagreement about a value — fix by removing the
  extra row 1012.
- **The Halcyon close date is a genuine timing disagreement** (March vs
  February) that must be flagged, even though it leaves the total unchanged.
- **There are NO cosmetic differences in these files.** Names, ids, dates, and
  number formats agree everywhere; the only differences between the two exports
  are the three genuine problems above. The correct classification says exactly
  that, rather than manufacturing cosmetic findings to fill the category.

**Assumption stated:** the CRM's 15,000 for Everest is treated as correct pending
confirmation with the deal owner.
