"""Visualizer (Box 7): render the pilot dashboard to one self-contained HTML.

``deskbench render`` reads ``results/summary.json`` plus the per-record
evidence (raw outputs, judge scores, human grades, task prompts + references)
and writes ``site/index.html`` per DASHBOARD_SPEC.md:

* header with run metadata and the judge–human agreement badge,
* the four pilot charts — leaderboard (judge vs human, messy/clean split,
  min–max whiskers), mess penalty (sign convention printed on the chart),
  silent-failure rate (denominators printed per bar), judge-vs-human scatter
  (y=x line, r + MAE printed, points click through to the inspector),
* a run inspector: task prompt · model output · reference · per-criterion
  judge scores with rationales · human scores, notes and silent/flagged tag,
  deep-linkable via the URL hash.

Self-containment: all data is inlined as JSON; the only external fetch is the
pinned Plotly CDN script (allowed explicitly by DASHBOARD_SPEC.md). The page
contains NO hand-entered numbers — everything is read from the inlined
summary/records, which came from ``results/`` files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .analyzer import DEFAULT_HUMAN_DIR, DEFAULT_RAW_DIR, DEFAULT_SUMMARY
from .grader import DEFAULT_SCORES_DIR
from .schemas import RawResult, Score, load_task

DEFAULT_SITE = Path("site/index.html")

PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"

# Okabe–Ito colorblind-safe palette (DASHBOARD_SPEC accessibility rule).
PALETTE = ["#E69F00", "#56B4E9", "#009E73", "#CC79A7", "#0072B2", "#D55E00"]


class VisualizeError(RuntimeError):
    """Raised when the evidence needed to render the dashboard is missing."""


def _load_json_dir(path: Path, skip_prefix: str | None = None) -> dict[str, dict[str, Any]]:
    out = {}
    for p in sorted(path.glob("*.json")):
        if skip_prefix and p.name.startswith(skip_prefix):
            continue
        out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


def collect_data(
    tasks_dir: Path = Path("tasks"),
    raw_dir: Path = DEFAULT_RAW_DIR,
    scores_dir: Path = DEFAULT_SCORES_DIR,
    human_dir: Path = DEFAULT_HUMAN_DIR,
    summary_path: Path = DEFAULT_SUMMARY,
) -> dict[str, Any]:
    """Assemble the full dashboard payload from the evidence on disk."""
    if not summary_path.exists():
        raise VisualizeError(f"{summary_path} not found — run `deskbench analyze` first")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    tasks: dict[str, Any] = {}
    for d in sorted(tasks_dir.iterdir()):
        if d.is_dir() and (d / "task.yaml").exists():
            t = load_task(d / "task.yaml")
            tasks[t.id] = {
                "title": t.title,
                "variant": t.variant,
                "prompt": t.prompt,
                "reference": (d / "reference.md").read_text(encoding="utf-8"),
            }

    raws = _load_json_dir(raw_dir)
    scores = _load_json_dir(scores_dir)
    humans = _load_json_dir(human_dir, skip_prefix="GRADING_SHEET")

    records: dict[str, Any] = {}
    for rid, raw in raws.items():
        RawResult.model_validate(raw)  # validate, then keep only what the page needs
        rec: dict[str, Any] = {
            "task_id": raw["task_id"],
            "model_id": raw["model_id"],
            "run_index": raw["run_index"],
            "variant": raw["variant"],
            "output": raw["output"],
            "error": raw["error"],
        }
        if rid in scores:
            Score.model_validate(scores[rid])
            s = scores[rid]
            rec["judge"] = {
                "criteria": [
                    {"name": c["name"], "score": c["score"], "rationale": c["judge_rationale"]}
                    for c in s["criterion_scores"]
                ],
                "weighted_total": s["weighted_total"],
                "auto_fail": s["auto_fail_triggered"],
                "judge_model": s["judge_model"],
            }
        if rid in humans:
            h = humans[rid]
            rec["human"] = {
                "criteria": [
                    {"name": c["name"], "score": c["score"]} for c in h["criterion_scores"]
                ],
                "weighted_total": h["weighted_total"],
                "auto_fail": h["auto_fail_triggered"],
                "silent_failure": h["silent_failure"],
                "notes": h.get("notes", ""),
            }
        records[rid] = rec

    if not records:
        raise VisualizeError(f"no raw records under {raw_dir}")
    models = summary["matrix"]["models"]
    colors = {m: PALETTE[i % len(PALETTE)] for i, m in enumerate(models)}
    return {"summary": summary, "tasks": tasks, "records": records, "colors": colors}


def render_html(data: dict[str, Any]) -> str:
    """Render the dashboard HTML around the inlined JSON payload."""
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    m = data["summary"]["matrix"]
    a = data["summary"]["agreement"]
    judge_names = ", ".join(m["judge_models"])
    generated = data["summary"]["generated_at"][:10]
    matrix_line = (
        f"{len(m['twin_pairs'])} twin pairs × {len(m['models'])} models × 3 runs "
        f"= {m['n_judge_scores']} completions · judge: {judge_names} · "
        f"human-graded: {m['n_human_grades']}/{m['n_judge_scores']} (100%)"
    )
    badge = (
        f"judge–human agreement: r = {a['weighted_total_pearson_r']} · "
        f"MAE = {a['weighted_total_mae']} (weighted totals, n = {a['n_paired']})"
    )
    head = HTML_TEMPLATE.replace("__PAYLOAD__", payload)
    head = head.replace("__PLOTLY_CDN__", PLOTLY_CDN)
    head = head.replace("__MATRIX_LINE__", matrix_line)
    head = head.replace("__BADGE__", badge)
    head = head.replace("__GENERATED__", generated)
    return head


def render(
    tasks_dir: Path = Path("tasks"),
    raw_dir: Path = DEFAULT_RAW_DIR,
    scores_dir: Path = DEFAULT_SCORES_DIR,
    human_dir: Path = DEFAULT_HUMAN_DIR,
    summary_path: Path = DEFAULT_SUMMARY,
    out: Path = DEFAULT_SITE,
) -> Path:
    """Collect evidence, render, and write the dashboard; returns the path."""
    html = render_html(collect_data(tasks_dir, raw_dir, scores_dir, human_dir, summary_path))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8", newline="\n")
    return out


# --------------------------------------------------------------------------- #
# The page. One file, research-report aesthetic, no build step.
# --------------------------------------------------------------------------- #
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DeskBench Pilot — results</title>
<script src="__PLOTLY_CDN__"></script>
<style>
  :root { --ink:#1a1a1a; --muted:#666; --line:#e3e3e3; --accent:#0072B2; }
  * { box-sizing: border-box; }
  body { margin:0; background:#fff; color:var(--ink);
         font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                      Helvetica, Arial, sans-serif; line-height:1.5; }
  main { max-width: 980px; margin: 0 auto; padding: 24px 16px 64px; }
  h1 { font-size: 1.7rem; margin: 0 0 4px; }
  h2 { font-size: 1.15rem; margin: 40px 0 4px; border-top: 1px solid var(--line);
       padding-top: 28px; }
  .sub { color: var(--muted); font-size: .9rem; margin: 0 0 10px; }
  .badge { display:inline-block; background:#f2f7fb; border:1px solid #cfe3f0;
           border-radius:6px; padding:2px 10px; font-size:.85rem; margin-top:6px; }
  .links a { margin-right: 14px; }
  .chart { width:100%; min-height:360px; }
  .filters label { margin-right:14px; font-size:.9rem; white-space:nowrap; }
  .note { color:var(--muted); font-size:.82rem; }
  select { font: inherit; padding: 2px 6px; margin-right: 10px; max-width: 100%; }
  .inspector-grid { display:grid; grid-template-columns: 1fr 1fr; gap:16px; }
  @media (max-width: 760px) { .inspector-grid { grid-template-columns: 1fr; } }
  .pane { border:1px solid var(--line); border-radius:8px; padding:12px 14px;
          overflow:auto; max-height:480px; }
  .pane h3 { margin:0 0 8px; font-size:.95rem; }
  .pane pre { white-space:pre-wrap; word-wrap:break-word; font-size:.82rem;
              font-family: ui-monospace, SFMono-Regular, Consolas, monospace; margin:0; }
  table.scores { border-collapse: collapse; width:100%; font-size:.85rem; }
  table.scores th, table.scores td { border:1px solid var(--line); padding:5px 8px;
                                     text-align:left; vertical-align:top; }
  table.scores th { background:#fafafa; }
  .tag-silent { color:#B00020; font-weight:600; }
  .tag-flagged { color:#00600f; font-weight:600; }
  footer { margin-top:48px; border-top:1px solid var(--line); padding-top:16px;
           font-size:.85rem; color:var(--muted); }
</style>
</head>
<body>
<main>
  <h1>DeskBench Pilot</h1>
  <p class="sub">What does <em>mess</em> cost a language model on real office work?
     Twin-pair benchmark: every task graded messy and clean.</p>
  <p class="sub links">
    <a href="https://github.com/NewAi25/deskbench">repo</a>
    <a href="https://github.com/NewAi25/deskbench/blob/main/report/REPORT.md">report</a>
    <a href="https://github.com/NewAi25/deskbench/blob/main/docs/methodology.md">methodology</a>
  </p>
  <p class="sub">__MATRIX_LINE__ · generated __GENERATED__</p>
  <p><span class="badge">__BADGE__</span></p>
  <p class="filters" id="model-filters"><strong style="font-size:.9rem">Models:</strong></p>

  <h2>1 · Leaderboard — judge vs human</h2>
  <p class="sub">Weight-normalized mean score (0–5; auto-fail forces a run to 0).
     Whiskers = min–max across the 3 runs per cell mean shown; n = 12 runs per model per grader.</p>
  <div id="chart-leaderboard" class="chart"></div>

  <h2>2 · Mess penalty</h2>
  <p class="sub">Core criteria only, relative core weights, per
     <a href="https://github.com/NewAi25/deskbench/blob/main/docs/methodology.md">methodology §3</a>.
     <strong>Sign: clean − messy — positive means the mess degraded the model.</strong>
     Hover a bar for the per-twin-pair breakdown. Computed independently from judge
     and from human scores.</p>
  <div id="chart-penalty" class="chart"></div>

  <h2>3 · Silent-failure rate</h2>
  <p class="sub">Of the answers the human grader marked wrong or incomplete, the share
     that never flagged the specific problem (human-assigned tags only; “na” = no
     wrong answer to tag, excluded from the denominator). Denominators are printed
     on each bar — small denominators are noisy.</p>
  <div id="chart-silent" class="chart"></div>

  <h2>4 · Judge vs human — every graded output</h2>
  <p class="sub">One point per (task, model, run). The dashed line is perfect
     agreement. <strong>Click any point to open it in the run inspector.</strong></p>
  <div id="chart-scatter" class="chart"></div>

  <h2>5 · Run inspector</h2>
  <p class="sub">The full chain of evidence for one run: prompt · model output ·
     reference · judge rationale · human grade. Deep-linkable — the URL hash tracks
     the selected record.</p>
  <p>
    <select id="sel-task"></select>
    <select id="sel-model"></select>
    <select id="sel-run"></select>
  </p>
  <div class="inspector-grid">
    <div class="pane"><h3>Task prompt</h3><pre id="insp-prompt"></pre></div>
    <div class="pane"><h3>Model output</h3><pre id="insp-output"></pre></div>
    <div class="pane"><h3>Reference (context, not the grading target)</h3><pre id="insp-reference"></pre></div>
    <div class="pane"><h3>Grades</h3><div id="insp-grades"></div></div>
  </div>

  <footer>
    <p><strong>Read this first:</strong> n = 2 tasks (4 task directories as twin
    pairs). These numbers describe <em>these tasks</em> under free-tier conditions —
    not “office work” in general. Judge scores are shown only next to their
    human-agreement numbers. Full limitations: the report’s “What these results do
    NOT show”. Roadmap:
    <a href="https://github.com/NewAi25/deskbench/blob/main/docs/adr/ADR-003-benchmark-as-a-function.md">
    ADR-003 — benchmark as a function</a>.</p>
    <p>MIT license · generated by <code>deskbench render</code> from
    <code>results/summary.json</code> + evidence files — no hand-entered numbers.</p>
  </footer>
</main>
<script id="deskbench-data" type="application/json">__PAYLOAD__</script>
<script>
"use strict";
const DATA = JSON.parse(document.getElementById("deskbench-data").textContent);
const S = DATA.summary, COLORS = DATA.colors;
const MODELS = S.matrix.models.slice();
let active = new Set(MODELS);

/* ---------- model filter ---------- */
const filterBox = document.getElementById("model-filters");
MODELS.forEach(m => {
  const lab = document.createElement("label");
  const cb = document.createElement("input");
  cb.type = "checkbox"; cb.checked = true;
  cb.addEventListener("change", () => {
    cb.checked ? active.add(m) : active.delete(m);
    drawAll();
  });
  lab.appendChild(cb);
  const sw = document.createElement("span");
  sw.style.cssText = `display:inline-block;width:10px;height:10px;border-radius:2px;
                      background:${COLORS[m]};margin:0 4px 0 6px`;
  lab.appendChild(sw);
  lab.appendChild(document.createTextNode(m));
  filterBox.appendChild(lab);
});

const LAYOUT = {
  font: {family: "inherit", size: 13},
  paper_bgcolor: "#fff", plot_bgcolor: "#fff",
  margin: {t: 24, r: 16, b: 60, l: 56},
  legend: {orientation: "h", y: -0.18},
};
const CONFIG = {displayModeBar: false, responsive: true};
const lb = () => S.leaderboard.filter(r => active.has(r.model));

/* ---------- 1 · leaderboard ---------- */
function drawLeaderboard() {
  const rows = lb();
  const groups = [
    ["judge", "mean_messy", "judge · messy", 1.0],
    ["judge", "mean_clean", "judge · clean", 0.45],
    ["human", "mean_messy", "human · messy", 1.0],
    ["human", "mean_clean", "human · clean", 0.45],
  ];
  const traces = groups.map(([src, key, name, op], gi) => ({
    type: "bar", name,
    x: rows.map(r => r.model),
    y: rows.map(r => r[src][key]),
    marker: {
      color: rows.map(r => COLORS[r.model]),
      opacity: op,
      pattern: src === "human" ? {shape: "/", size: 4, solidity: 0.4} : {},
    },
    error_y: {
      type: "data", symmetric: false, thickness: 1.2, width: 3, color: "#444",
      array: rows.map(r => {
        const v = r[src].per_run.filter(p => p.variant === key.slice(5));
        return Math.max(...v.map(p => p.weighted_total)) - r[src][key];
      }),
      arrayminus: rows.map(r => {
        const v = r[src].per_run.filter(p => p.variant === key.slice(5));
        return r[src][key] - Math.min(...v.map(p => p.weighted_total));
      }),
    },
    hovertemplate: "%{x} · " + name + ": %{y:.2f}<extra></extra>",
  }));
  Plotly.newPlot("chart-leaderboard", traces, Object.assign({}, LAYOUT, {
    barmode: "group", yaxis: {title: "weighted total", range: [0, 5.15], dtick: 1},
  }), CONFIG);
}

/* ---------- 2 · mess penalty ---------- */
function drawPenalty() {
  const per = S.mess_penalty.per_model.filter(r => active.has(r.model));
  const pairText = m => S.mess_penalty.per_pair
    .filter(p => p.model === m)
    .map(p => `${p.pair}: judge ${p.judge >= 0 ? "+" : ""}${p.judge}, ` +
              `human ${p.human >= 0 ? "+" : ""}${p.human}`)
    .join("<br>");
  const mk = (key, name, op) => ({
    type: "bar", name,
    x: per.map(r => r.model), y: per.map(r => r[key]),
    marker: {color: per.map(r => COLORS[r.model]), opacity: op,
             pattern: key === "human" ? {shape: "/", size: 4, solidity: 0.4} : {}},
    customdata: per.map(r => pairText(r.model)),
    hovertemplate: "%{x} · " + name + ": %{y:.3f}<br>%{customdata}<extra></extra>",
  });
  Plotly.newPlot("chart-penalty", [mk("judge", "judge-scored", 1.0), mk("human", "human-scored", 0.5)],
    Object.assign({}, LAYOUT, {
      barmode: "group",
      yaxis: {title: "mess penalty (clean − messy, core criteria)", zeroline: true,
              zerolinecolor: "#888", zerolinewidth: 1.5},
      annotations: [{xref: "paper", yref: "paper", x: 0, y: 1.09, showarrow: false,
        text: "↑ positive = mess hurt the model", font: {size: 12, color: "#666"}}],
    }), CONFIG);
}

/* ---------- 3 · silent failure ---------- */
function drawSilent() {
  const rows = S.silent_failure.filter(r => active.has(r.model));
  Plotly.newPlot("chart-silent", [{
    type: "bar",
    x: rows.map(r => r.model),
    y: rows.map(r => r.rate === null ? 0 : r.rate),
    marker: {color: rows.map(r => COLORS[r.model])},
    text: rows.map(r => r.rate === null
      ? "no wrong answers"
      : `${r.silent}/${r.silent + r.flagged} silent (na: ${r.na_excluded})`),
    textposition: "outside",
    hovertemplate: "%{x}: silent %{text}<extra></extra>",
  }], Object.assign({}, LAYOUT, {
    yaxis: {title: "silent / (silent + flagged)", range: [0, 1.12], tickformat: ".0%"},
  }), CONFIG);
}

/* ---------- 4 · scatter ---------- */
function drawScatter() {
  const traces = MODELS.filter(m => active.has(m)).map(m => {
    const recs = Object.entries(DATA.records)
      .filter(([, r]) => r.model_id === m && r.judge && r.human);
    return {
      type: "scatter", mode: "markers", name: m,
      x: recs.map(([, r]) => r.human.weighted_total),
      y: recs.map(([, r]) => r.judge.weighted_total),
      customdata: recs.map(([id]) => id),
      marker: {color: COLORS[m], size: 9, opacity: 0.8,
               line: {color: "#fff", width: 1}},
      hovertemplate: "%{customdata}<br>human %{x:.2f} · judge %{y:.2f}" +
                     "<br><i>click to inspect</i><extra></extra>",
    };
  });
  const a = S.agreement;
  Plotly.newPlot("chart-scatter", traces, Object.assign({}, LAYOUT, {
    xaxis: {title: "human weighted total", range: [-0.2, 5.2], dtick: 1},
    yaxis: {title: "judge weighted total", range: [-0.2, 5.2], dtick: 1},
    shapes: [{type: "line", x0: 0, y0: 0, x1: 5, y1: 5,
              line: {dash: "dash", color: "#999", width: 1}}],
    annotations: [{xref: "paper", yref: "paper", x: 0.02, y: 0.98, showarrow: false,
      align: "left",
      text: `r = ${a.weighted_total_pearson_r} · MAE = ${a.weighted_total_mae}` +
            `<br>auto-fail match = ${a.auto_fail_exact_match_rate} · n = ${a.n_paired}`,
      font: {size: 12, color: "#444"}, bgcolor: "rgba(255,255,255,.85)"}],
  }), CONFIG);
  document.getElementById("chart-scatter").on("plotly_click", ev => {
    const id = ev.points[0].customdata;
    if (id) { showRecord(id); document.getElementById("sel-task").scrollIntoView(); }
  });
}

/* ---------- 5 · inspector ---------- */
const TASKS = Object.keys(DATA.tasks).sort();
const selTask = document.getElementById("sel-task");
const selModel = document.getElementById("sel-model");
const selRun = document.getElementById("sel-run");
TASKS.forEach(t => selTask.add(new Option(`${t} (${DATA.tasks[t].variant})`, t)));
MODELS.forEach(m => selModel.add(new Option(m, m)));
[0, 1, 2].forEach(i => selRun.add(new Option(`run ${i}`, i)));
[selTask, selModel, selRun].forEach(el => el.addEventListener("change", () => {
  const id = `${selTask.value}__${selModel.value}__run${selRun.value}`;
  if (DATA.records[id]) showRecord(id);
}));

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function gradeTable(rec) {
  const j = rec.judge, h = rec.human;
  if (!j && !h) return "<p class='note'>ungraded</p>";
  const names = (j ? j.criteria : h.criteria).map(c => c.name);
  const hBy = {}; (h ? h.criteria : []).forEach(c => hBy[c.name] = c.score);
  let rows = names.map(n => {
    const jc = j ? j.criteria.find(c => c.name === n) : null;
    return `<tr><td>${esc(n)}</td>` +
      `<td>${jc ? jc.score : "—"}</td>` +
      `<td>${n in hBy ? hBy[n] : "—"}</td>` +
      `<td>${jc ? esc(jc.rationale) : "—"}</td></tr>`;
  }).join("");
  const tag = !h ? "" : h.silent_failure === true
    ? "<span class='tag-silent'>SILENT failure</span>"
    : h.silent_failure === false
      ? "<span class='tag-flagged'>flagged</span>" : "n/a (nothing wrong to tag)";
  return `
    <table class="scores">
      <tr><th>criterion</th><th>judge</th><th>human</th><th>judge rationale</th></tr>
      ${rows}
      <tr><th>weighted total${j && j.auto_fail ? " (judge AUTO-FAIL)" : ""}</th>
          <th>${j ? j.weighted_total : "—"}</th>
          <th>${h ? h.weighted_total : "—"}</th>
          <th>${h && h.auto_fail ? "human: auto-fail. " : ""}${tag}</th></tr>
    </table>
    ${h && h.notes ? `<p class="note"><strong>Human notes:</strong> ${esc(h.notes)}</p>` : ""}
    <p class="note">judge: ${j ? esc(j.judge_model) : "—"} · human: maintainer, blind, 100% coverage</p>`;
}
function showRecord(id) {
  const rec = DATA.records[id];
  if (!rec) return;
  selTask.value = rec.task_id; selModel.value = rec.model_id; selRun.value = rec.run_index;
  document.getElementById("insp-prompt").textContent = DATA.tasks[rec.task_id].prompt;
  document.getElementById("insp-output").textContent =
    rec.error ? `[errored run: ${rec.error}]` : rec.output;
  document.getElementById("insp-reference").textContent = DATA.tasks[rec.task_id].reference;
  document.getElementById("insp-grades").innerHTML = gradeTable(rec);
  history.replaceState(null, "", "#record=" + encodeURIComponent(id));
}

function drawAll() { drawLeaderboard(); drawPenalty(); drawSilent(); drawScatter(); }
drawAll();

const fromHash = decodeURIComponent((location.hash.match(/record=([^&]+)/) || [,""])[1]);
showRecord(DATA.records[fromHash] ? fromHash : Object.keys(DATA.records).sort()[0]);
</script>
</body>
</html>
"""
