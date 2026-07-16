#!/usr/bin/env python3
"""Independent on-disk verification of the T02 / T02c twin pair.

**Companion to the ADR-003 generator prototype** (``scripts/gen_t02.py``). Where
the generator asserts the twin invariants over the values it is about to write,
this script re-derives them from the *committed* CSV files — through DeskBench's
own schema loaders — so the guarantees hold for whatever is actually on disk,
not just for a fresh generator run. Under the ADR-003 v2 design this becomes the
"diversity/consistency audit" every template ships with; here it audits the one
hand-built instance.

Checks, all from disk:
  1. Twin values identical — CRM (amount, date) per deal and the finance
     (id, amount, date) multiset match between the messy and clean twins.
  2. The CRM-vs-finance gap reconciles EXACTLY to the sum of the planted errors
     (duplicate +8,400, Everest dropped zero -13,500).
  3. Prompts are byte-identical across the pair, and the twin-pair rubric
     contract holds (shared core criteria at identical weights; messy weights
     sum to 1.0).

Usage::

    python scripts/verify_t02.py        # exits non-zero on any invariant failure
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from deskbench import schemas

REPO = Path(__file__).resolve().parents[1]
T02 = REPO / "tasks" / "T02-spreadsheet-reconciliation"
T02C = REPO / "tasks" / "T02c-spreadsheet-reconciliation"

DUP_ID, MAG_ID, MONTH_ID = 1012, 1019, 1008


def _num(s: str) -> float:
    return float(s.replace("$", "").replace(",", "").strip())


def _iso(datestr: str, dmy: bool) -> str:
    if "-" in datestr:
        return datestr  # already ISO (clean)
    a, b, y = datestr.split("/")
    return f"{y}-{b}-{a}" if dmy else f"{y}-{a}-{b}"  # dmy: DD/MM ; else MM/DD


def _load_csv(path: Path) -> list[list[str]]:
    return list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))[1:]


def _deals_from(crm_path: Path, fin_path: Path, *, messy: bool):
    crm = {int(r[0]): (_num(r[3]), _iso(r[2], dmy=False)) for r in _load_csv(crm_path)}
    fin = []  # (id, amount, iso_date)
    for r in _load_csv(fin_path):
        did = int(r[0].replace("INV-", "")) if messy else int(r[0])
        fin.append((did, _num(r[3]), _iso(r[2], dmy=messy)))
    return crm, fin


def main() -> None:
    mcrm, mfin = _deals_from(
        T02 / "artifacts/crm_export.csv", T02 / "artifacts/finance_ledger.csv", messy=True
    )
    ccrm, cfin = _deals_from(
        T02C / "artifacts/crm_export.csv", T02C / "artifacts/finance_ledger.csv", messy=False
    )

    # 1. Twin arithmetic identical (values recovered from disk).
    assert {k: v[0] for k, v in mcrm.items()} == {k: v[0] for k, v in ccrm.items()}, "CRM amts"
    assert {k: v[1] for k, v in mcrm.items()} == {k: v[1] for k, v in ccrm.items()}, "CRM dates"
    assert sorted(mfin) == sorted(cfin), "finance (id,amount,date) multiset differs"

    crm_total = sum(v[0] for v in mcrm.values())
    fin_total = sum(a for _d, a, _dt in mfin)
    clean_crm_total = sum(v[0] for v in ccrm.values())
    clean_fin_total = sum(a for _d, a, _dt in cfin)

    # 2. Gap reconciles EXACTLY to the planted errors.
    dup_amt = mcrm[DUP_ID][0]
    mag_true = mcrm[MAG_ID][0]
    mag_fin = next(a for d, a, _ in mfin if d == MAG_ID)
    mag_loss = mag_true - mag_fin
    gap = crm_total - fin_total
    dup_count = sum(1 for d, _a, _ in mfin if d == DUP_ID)

    assert fin_total == crm_total + dup_amt - mag_loss, "finance != crm + dup - mag_loss"
    assert gap == mag_loss - dup_amt, "gap != mag_loss - dup"
    assert dup_count == 2, f"duplicate not present exactly twice: {dup_count}"

    crm_month = mcrm[MONTH_ID][1]
    fin_month = next(dt for d, _a, dt in mfin if d == MONTH_ID)
    assert crm_month.split("-")[1] != fin_month.split("-")[1], "Halcyon months should differ"
    assert crm_month.split("-")[2] == fin_month.split("-")[2], "Halcyon day should match"

    # 3. Prompts byte-identical + twin-pair rubric contract.
    t = schemas.load_task(T02 / "task.yaml")
    tc = schemas.load_task(T02C / "task.yaml")
    assert t.prompt == tc.prompt, "prompts differ across twin pair"

    rm = schemas.load_rubric(T02 / "rubric.yaml")
    rc = schemas.load_rubric(T02C / "rubric.yaml")
    core_messy = {c.name: c for c in rm.criteria if c.kind == "core"}
    assert abs(sum(c.weight for c in rm.criteria) - 1.0) < 1e-9, "messy weights must sum to 1.0"
    assert {c.name for c in rc.criteria} == set(core_messy), "clean criteria != messy core"
    for c in rc.criteria:
        assert c.kind == "core" and c.weight == core_messy[c.name].weight, f"weight {c.name}"
    assert [c for c in rm.criteria if c.kind == "mess"], "messy rubric needs a mess criterion"

    mfin_rows = len(_load_csv(T02 / "artifacts/finance_ledger.csv"))
    print("=== T02 / T02c hardened pair — on-disk verification ===")
    print(f"CRM rows / finance rows          : {len(mcrm)} / {mfin_rows}  (27 deals + 1 dup)")
    print(f"CRM total     (messy == clean)   : {crm_total:,.2f} == {clean_crm_total:,.2f}")
    print(f"Finance total (messy == clean)   : {fin_total:,.2f} == {clean_fin_total:,.2f}")
    print(f"Twin finance (id,amt,date) sets  : IDENTICAL -> {sorted(mfin) == sorted(cfin)}")
    print(f"Gap (CRM - finance)              : {gap:,.2f}")
    print(f"  Bluecrest {DUP_ID} duplicate     : +{dup_amt:,.2f} (appears {dup_count}x)")
    print(
        f"  Everest {MAG_ID} dropped zero    : -{mag_loss:,.2f} ({mag_true:,.0f}->{mag_fin:,.0f})"
    )
    recon = f"{crm_total:,.0f} + {dup_amt:,.0f} - {mag_loss:,.0f} = {fin_total:,.0f}"
    print(f"  reconciliation                 : {recon}")
    print(
        f"Halcyon {MONTH_ID} wrong-month      : CRM {crm_month} vs finance {fin_month} (0 effect)"
    )
    print(f"Everest-if-1,500 total           : {crm_total - mag_loss:,.2f}")
    print(f"Prompts byte-identical (pair)    : {t.prompt == tc.prompt}")
    print(f"Clean core == messy core weights : sum {sum(c.weight for c in rc.criteria):.2f}")
    print("\nALL INVARIANTS PASS")


if __name__ == "__main__":
    main()
