"""Tests for the dashboard renderer against the committed pilot evidence.

The dashboard is generated output; what must never regress is the data
contract: it embeds the real summary + records, escapes the payload safely,
renders every section the spec promises, and contains no hand-entered numbers
(spot-checked by asserting computed values appear verbatim from summary.json).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deskbench.visualize import collect_data, render_html

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def html() -> str:
    if not (REPO / "results" / "summary.json").exists():
        pytest.skip("pilot evidence not present")
    data = collect_data(
        REPO / "tasks",
        REPO / "results" / "raw",
        REPO / "results" / "scores",
        REPO / "results" / "human",
        REPO / "results" / "summary.json",
    )
    return render_html(data)


def test_payload_embeds_all_records(html):
    payload = html.split('type="application/json">')[1].split("</script>")[0]
    data = json.loads(payload.replace("<\\/", "</"))
    assert len(data["records"]) == 48
    assert data["summary"]["matrix"]["n_human_grades"] == 48
    # Inspector needs the full chain for every record.
    rec = next(iter(data["records"].values()))
    assert {"task_id", "model_id", "variant", "output"} <= set(rec)
    assert "criteria" in rec["judge"] and "rationale" in rec["judge"]["criteria"][0]
    assert "silent_failure" in rec["human"]


def test_all_sections_present(html):
    for section_id in (
        "chart-leaderboard",
        "chart-penalty",
        "chart-silent",
        "chart-scatter",
        "insp-output",
        "insp-reference",
        "insp-grades",
        "model-filters",
    ):
        assert section_id in html, f"missing dashboard section {section_id}"
    # Spec: sign convention printed on the mess-penalty chart; n=2 note in footer.
    assert "positive = mess hurt the model" in html
    assert "n = 2 tasks" in html


def test_numbers_come_from_summary(html):
    # The agreement badge must carry the exact computed values, not prose.
    summary = json.loads((REPO / "results" / "summary.json").read_text(encoding="utf-8"))
    a = summary["agreement"]
    assert f"r = {a['weighted_total_pearson_r']}" in html
    assert f"MAE = {a['weighted_total_mae']}" in html


def test_payload_script_safe(html):
    # No raw '</' inside the JSON payload (would terminate the script tag early).
    payload = html.split('type="application/json">')[1].split("</script>")[0]
    assert "</" not in payload.replace("<\\/", "")


def test_single_file_no_local_asset_refs(html):
    # Self-contained: the only external ref is the pinned Plotly CDN.
    assert html.count("<script src=") == 1
    assert "cdn.plot.ly/plotly-2" in html
    assert 'href="site/' not in html and "file:///" not in html
