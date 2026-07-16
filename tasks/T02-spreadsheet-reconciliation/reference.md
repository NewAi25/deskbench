# Reference answer — T02 Spreadsheet Reconciliation

*Written before any model was run. Grade against the rubric anchors, not against
exact wording. The numeric conclusions, however, are determinate.*

The two files describe the same 27 Q1 deals (IDs 1001–1027). Almost every row
differs **cosmetically** between the systems; only three rows carry a **genuine**
discrepancy, and only two of those move the total.

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

## 2. The genuine discrepancies (the only rows that are not merely cosmetic)

| Deal | CRM | Finance | Classification |
|------|-----|---------|----------------|
| Bluecrest (1012) | Bluecrest Ltd, $8,400.00, one row | Bluecrest Limited, 8,400.00 — **appears twice** (INV-1012 listed again lower in the file, after Tidewater 1021) | **Genuine (duplicate)** — the ledger double-counts INV-1012 (+8,400). Remove one row. The name/format differences are cosmetic. |
| Everest (1019) | Everest Retail, $15,000.00 | Everest Retail, 1,500.00 | **Genuine data error** — the amounts truly disagree (15,000 vs 1,500), a dropped zero in finance (−13,500). This is the one *amount* error to correct. |
| Halcyon (1008) | Halcyon Travel, 03/05/2024 (5 Mar) | Halcyon Travel, 05/02/2024 (5 Feb) | **Genuine timing discrepancy** — the two systems disagree on the *close month* (March vs February), not on the amount (11,200 in both). It does **not** change the Q1 total, but it is a real data disagreement to flag, not a formatting artifact. |

Reconciliation of the 5,100 gap: finance is inflated **+8,400** by the Bluecrest
duplicate and deflated **−13,500** by the Everest dropped zero → net **−5,100**,
exactly the observed difference (375,740 − 370,640). The Halcyon month mismatch
nets to zero (same amount both sides) and so does not enter the total.

## 3. The real error vs. the cosmetic noise

- **The single genuine *amount* error to correct is Everest (INV-1019): 1,500 vs
  15,000** — almost certainly a dropped zero; confirm with the deal owner.
- **The Bluecrest duplicate is a genuine ledger problem too**, but it is a
  data-entry duplication, not a disagreement about a value — fix by removing the
  extra INV-1012 row.
- **The Halcyon close date is a genuine timing disagreement** (March vs
  February) that must be flagged, even though it leaves the total unchanged.
- **Everything else is cosmetic** and appears on essentially every row:
  company-name variants (Acme Corp / ACME Corporation, Ltd / Limited, case
  changes such as "cirrus analytics", "&" vs "and", a trailing space on
  "Bluecrest Limited "), transaction-id prefixing (CRM `1001` vs finance
  `INV-1001`), currency formatting ($, commas, decimals), and the date-format
  mismatch (CRM MM/DD/YYYY vs finance DD/MM/YYYY — equivalent for all 26
  non-Halcyon rows).

**Assumptions stated:** (1) the CRM's 15,000 for Everest is treated as correct
pending confirmation; (2) dates are read as MM/DD in the CRM and DD/MM in
finance, which makes every row except Halcyon a pure format difference; under
that convention Halcyon genuinely disagrees (5 Mar vs 5 Feb) and is flagged
rather than silently resolved.
