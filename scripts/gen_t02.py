#!/usr/bin/env python3
"""Single source of truth for the T02 / T02c reconciliation twin pair.

**Hand-rolled prototype of the ADR-003 generator design** ("Benchmark as a
function, not a list"). ADR-003 proposes that a v2 task be a parameterized
template — ``generate(template, seed) -> (artifacts, reference, rubric)`` — with
core parameters that change the answer, noise parameters whose ``off`` position
*is* the clean twin, and a reference derived by construction rather than hand-
written. This script is that idea applied by hand to one task:

* One ``DEALS`` table + three planted errors is the single source of truth.
* ``noise=on`` emits the messy T02 artifacts; ``noise=off`` emits the clean T02c
  artifacts with byte-identical underlying values — the twin, produced
  mechanically instead of hand-curated.
* Every twin invariant (identical CRM/finance values across the pair, the gap
  reconciling exactly to the planted errors, the duplicate appearing twice) is
  asserted in :func:`verify` before anything is written.

It is deliberately NOT the ADR-003 engine (no seeds, no template abstraction, no
computed rubric bindings): it is the existence proof ADR-003 §"the pilot is the
existence proof" calls for — the hand judgment a real generator must encode.

Usage::

    python scripts/gen_t02.py           # dry-run: build + verify, write nothing
    python scripts/gen_t02.py --write    # overwrite the T02/T02c CSV artifacts

Re-running with ``--write`` is idempotent: it reproduces the committed CSVs
byte-for-byte. Pair with ``scripts/verify_t02.py`` to re-check the on-disk files.
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
T02 = REPO / "tasks" / "T02-spreadsheet-reconciliation" / "artifacts"
T02C = REPO / "tasks" / "T02c-spreadsheet-reconciliation" / "artifacts"

# (id, canonical_customer, iso_close_date, true_amount, finance_name_variant)
# `finance_name_variant` is the messy finance rendering (cosmetic only); the
# clean twin uses `canonical_customer` in BOTH files.
DEALS = [
    (1001, "Acme Corp", "2024-03-04", 12000, "ACME Corporation"),
    (1002, "Northwind Traders", "2024-01-15", 22500, "Northwind Traders, Inc."),
    (1003, "Sterling Freight", "2024-01-22", 4750, "Sterling Freight Co."),
    (1004, "Cirrus Analytics", "2024-02-05", 5250, "cirrus analytics"),
    (1005, "Delta Systems", "2024-02-12", 3000, "Delta Systems"),
    (1006, "Meridian Health", "2024-01-09", 31200, "Meridian Health Group"),
    (1007, "Pinnacle Foods", "2024-03-18", 6800, "Pinnacle Foods Ltd"),
    (1008, "Halcyon Travel", "2024-03-05", 11200, "Halcyon Travel"),  # WRONG-MONTH
    (1009, "Vantage Media", "2024-02-26", 9900, "Vantage Media LLC"),
    (1010, "Ironclad Security", "2024-01-30", 18400, "Ironclad Security"),
    (1011, "Quorum Legal", "2024-03-11", 2600, "Quorum Legal LLP"),
    (1012, "Bluecrest Ltd", "2024-02-14", 8400, "Bluecrest Limited "),  # DUPLICATE
    (1013, "Brightpath Education", "2024-01-19", 7350, "BrightPath Education"),
    (1014, "Cascade Utilities", "2024-02-20", 13750, "Cascade Utilities"),
    (1015, "Redwood Logistics", "2024-03-25", 5940, "Redwood Logistics, Inc"),
    (1016, "Summit Insurance", "2024-01-27", 27000, "Summit Insurance Co"),
    (1017, "Kestrel Robotics", "2024-02-08", 44800, "Kestrel Robotics"),
    (1018, "Onyx Consulting", "2024-03-14", 3850, "ONYX Consulting"),
    (1019, "Everest Retail", "2024-02-29", 15000, "Everest Retail"),  # MAGNITUDE
    (1020, "Larkspur Design", "2024-01-12", 6150, "Larkspur Design Studio"),
    (1021, "Tidewater Marine", "2024-03-21", 19750, "Tidewater Marine"),
    (1022, "Beacon Analytics", "2024-02-16", 8100, "Beacon Analytics"),
    (1023, "Fairmont Realty", "2024-01-24", 15600, "Fairmont Realty Group"),
    (1024, "Glenwood Pharma", "2024-03-08", 24300, "Glenwood Pharmaceuticals"),
    (1025, "Sable and Finch", "2024-02-03", 4200, "Sable & Finch"),
    (1026, "Ashcroft Industrial", "2024-01-17", 33500, "Ashcroft Industrial Ltd"),
    (1027, "Vireo Software", "2024-03-28", 10450, "Vireo Software"),
]

DUP_ID = 1012  # Bluecrest — duplicated row in finance
MAG_ID = 1019  # Everest — dropped zero (15000 -> 1500) in finance
MONTH_ID = 1008  # Halcyon — finance records Feb 05 instead of Mar 05
MONTH_FIN_ISO = "2024-02-05"  # genuine wrong-month date in finance (same day)
DUP_AFTER = 1021  # bury the duplicate row just after this deal
MAG_FIN_AMOUNT = 1500

by_id = {d[0]: d for d in DEALS}


# --------------------------------------------------------------------------- #
# Formatting helpers  (messy renderings must all parse back to the true value)
# --------------------------------------------------------------------------- #
def iso_to_mdy(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{m}/{d}/{y}"  # CRM style: MM/DD/YYYY


def iso_to_dmy(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"  # finance style: DD/MM/YYYY


def crm_amount(amount: int, i: int) -> str:
    """Messy CRM amount rendering — inconsistent, $-prefixed."""
    if amount % 1000 == 0 and i % 3 == 0:
        return f"${amount:,}"  # e.g. $3,000  (no decimals)
    if i % 5 == 0:
        return f"{amount}"  # e.g. 5250    (plain, no $, no commas)
    return f"${amount:,.2f}"  # e.g. $12,000.00


def fin_amount(amount: int, i: int) -> str:
    """Messy finance amount rendering — no $, mixed commas/decimals."""
    if i % 4 == 0:
        return f"{amount}"  # e.g. 5250
    if i % 2 == 0:
        return f"{amount:.2f}"  # e.g. 12000.00 (no commas)
    return f"{amount:,.2f}"  # e.g. 8,400.00 (commas)


def plain_amount(amount: int) -> str:
    """Clean rendering — one plain format everywhere."""
    return f"{amount:.2f}"


def to_csv(header: list[str], rows: list[list[str]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Build the four CSVs
# --------------------------------------------------------------------------- #
def build_crm(noise: bool) -> str:
    rows = []
    for i, (did, name, iso, amt, _fin) in enumerate(DEALS):
        if noise:
            rows.append([str(did), name, iso_to_mdy(iso), crm_amount(amt, i)])
        else:
            rows.append([str(did), name, iso, plain_amount(amt)])
    return to_csv(["Deal ID", "Customer", "Close Date", "Amount"], rows)


def build_finance(noise: bool) -> str:
    """ID order, plus the duplicate DUP_ID row re-listed after DUP_AFTER."""
    base = []
    for i, (did, name, iso, amt, fin) in enumerate(DEALS):
        fin_amt = MAG_FIN_AMOUNT if did == MAG_ID else amt
        fin_iso = MONTH_FIN_ISO if did == MONTH_ID else iso
        if noise:
            row = [f"INV-{did}", fin, iso_to_dmy(fin_iso), fin_amount(fin_amt, i)]
        else:
            row = [str(did), name, fin_iso, plain_amount(fin_amt)]
        base.append((did, row))
    rows = [r for _did, r in base]
    dup_row = next(r for did, r in base if did == DUP_ID)
    insert_at = [i for i, (did, _r) in enumerate(base) if did == DUP_AFTER][0] + 1
    rows.insert(insert_at, list(dup_row))
    return to_csv(["Txn", "Client", "Date", "Value"], rows)


# --------------------------------------------------------------------------- #
# Verification (twin invariants, enforced before any write)
# --------------------------------------------------------------------------- #
def _num(s: str) -> float:
    return float(s.replace("$", "").replace(",", "").strip())


def _rows(csv_text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(csv_text)))[1:]  # drop header


def _parse_mdy(s: str) -> str:
    m, d, y = s.split("/")
    return f"{y}-{m}-{d}"


def _parse_dmy(s: str) -> str:
    d, m, y = s.split("/")
    return f"{y}-{m}-{d}"


def _fin_triples(rows: list[list[str]], messy: bool) -> list[tuple[int, float, str]]:
    out = []
    for r in rows:
        did = int(r[0].replace("INV-", "")) if messy else int(r[0])
        amt = _num(r[3]) if messy else float(r[3])
        date = _parse_dmy(r[2]) if messy else r[2]
        out.append((did, amt, date))
    return out


def verify(messy_crm: str, messy_fin: str, clean_crm: str, clean_fin: str) -> None:
    true_total = sum(d[3] for d in DEALS)
    dup_amt = by_id[DUP_ID][3]
    mag_loss = by_id[MAG_ID][3] - MAG_FIN_AMOUNT

    m_crm = {int(r[0]): (_parse_mdy(r[2]), _num(r[3])) for r in _rows(messy_crm)}
    c_crm = {int(r[0]): (r[2], float(r[3])) for r in _rows(clean_crm)}
    m_fin = sorted(_fin_triples(_rows(messy_fin), messy=True))
    c_fin = sorted(_fin_triples(_rows(clean_fin), messy=False))

    # 1. Twin values identical (CRM amounts + dates, finance multiset).
    assert set(m_crm) == set(c_crm) == {d[0] for d in DEALS}
    for did in m_crm:
        assert m_crm[did][1] == c_crm[did][1] == float(by_id[did][3]), f"CRM amt {did}"
        assert m_crm[did][0] == c_crm[did][0], f"CRM date {did}"
    assert m_fin == c_fin, "finance underlying values differ across twins"

    # 2. Totals + gap reconcile exactly to the planted errors.
    crm_total = sum(v[1] for v in m_crm.values())
    fin_total = sum(a for _d, a, _dt in m_fin)
    assert crm_total == true_total
    assert fin_total == crm_total + dup_amt - mag_loss
    gap = crm_total - fin_total
    assert gap == mag_loss - dup_amt

    # 3. Structure of the three planted discrepancies.
    assert sum(1 for d, _a, _dt in m_fin if d == DUP_ID) == 2, "duplicate not twice"
    assert [a for d, a, _dt in m_fin if d == MAG_ID] == [float(MAG_FIN_AMOUNT)]
    crm_month = m_crm[MONTH_ID][0]
    fin_month = next(dt for d, _a, dt in m_fin if d == MONTH_ID)
    assert crm_month.split("-")[1] != fin_month.split("-")[1], "months should differ"
    assert crm_month.split("-")[2] == fin_month.split("-")[2], "day should match"

    print("=== T02 / T02c twin — verification ===")
    print(f"distinct deals             : {len(DEALS)}")
    print(f"CRM rows / finance rows    : {len(_rows(messy_crm))} / {len(_rows(messy_fin))}")
    print(f"CRM total  (== clean)      : {crm_total:,.2f}")
    print(f"finance total (== clean)   : {fin_total:,.2f}")
    print(f"gap (CRM - finance)        : {gap:,.2f}")
    print(f"  duplicate {DUP_ID} inflates: +{dup_amt:,.2f}")
    print(f"  magnitude {MAG_ID} deflates: -{mag_loss:,.2f}")
    print(f"  net == -gap              : {dup_amt - mag_loss:+,.2f}")
    print(f"wrong-month {MONTH_ID}       : CRM {crm_month} vs finance {fin_month} (0 total effect)")
    print(f"if Everest truly 1,500     : {crm_total - mag_loss:,.2f}")
    print("twin values identical + gap reconciles: PASS")


def main(write: bool) -> None:
    messy_crm, messy_fin = build_crm(noise=True), build_finance(noise=True)
    clean_crm, clean_fin = build_crm(noise=False), build_finance(noise=False)
    verify(messy_crm, messy_fin, clean_crm, clean_fin)
    if write:
        (T02 / "crm_export.csv").write_text(messy_crm, encoding="utf-8", newline="")
        (T02 / "finance_ledger.csv").write_text(messy_fin, encoding="utf-8", newline="")
        (T02C / "crm_export.csv").write_text(clean_crm, encoding="utf-8", newline="")
        (T02C / "finance_ledger.csv").write_text(clean_fin, encoding="utf-8", newline="")
        print("\nWROTE 4 CSVs.")
    else:
        print("\n(dry run — pass --write to overwrite the CSV artifacts)")


if __name__ == "__main__":
    main(write="--write" in sys.argv)
