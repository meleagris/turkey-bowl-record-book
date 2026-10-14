#!/usr/bin/env python3
"""Build the record book website from data/records.json into site/index.html.

Run after records.py. The page is a single self-contained file with the data
embedded, so it works on GitHub Pages and when opened straight from disk.
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RECORDS_PATH = ROOT / "data" / "records.json"
DB_PATH = ROOT / "data" / "league.db"
OUT_DIR = ROOT / "site"

records = json.loads(RECORDS_PATH.read_text())
con = sqlite3.connect(DB_PATH)
league_name = con.execute("SELECT name FROM seasons ORDER BY season DESC LIMIT 1").fetchone()[0] or "Record Book"
latest = con.execute("SELECT season, MAX(week) FROM games WHERE is_final = 1 "
                     "GROUP BY season ORDER BY season DESC LIMIT 1").fetchone()
if latest:
    records["generated_through"] = {"season": latest[0], "week": latest[1]}
con.close()

# Published newsletters: every newsletters/*.md whose front matter says status: published
issues = []
for f in sorted((ROOT / "newsletters").glob("*.md")):
    text = f.read_text(encoding="utf-8")
    meta, body = {}, text
    if text.startswith("---"):
        head, _, body = text[3:].partition("\n---")
        for line in head.strip().splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
        body = body.lstrip("-").lstrip("\n")
    if meta.get("status", "").lower() != "published":
        continue
    try:
        import markdown
        html = markdown.markdown(body, extensions=["tables", "sane_lists"])
    except ImportError:
        import html as _h
        html = "<pre>" + _h.escape(body) + "</pre>"
    issues.append({"season": meta.get("season", ""), "week": int(meta.get("week", 0) or 0),
                   "title": meta.get("title", f.stem), "html": html})
issues.sort(key=lambda i: (i["season"], i["week"]), reverse=True)
records["newsletters"] = issues
print(f"{len(issues)} published newsletter issue(s)")

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0d1229">
<title>__LEAGUE__ Record Book</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🦃</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@500;600;700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #0d1229;
  --panel: #161c3b;
  --panel-2: #1f2750;
  --line: #2b3463;
  --text: #f4f5fb;
  --muted: #8d95bd;
  --mint: #2ee6c5;
  --pink: #ff5c84;
  --gold: #ffcd3c;
  --qb: #ef8eb3; --rb: #a2f3d4; --wr: #75d2f8; --te: #fbbc78; --other: #bfbfbf;
  --head: "Poppins", "Segoe UI", system-ui, sans-serif;
  --body: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
  color-scheme: dark;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--bg); color: var(--text); font: 400 15px/1.45 var(--body); font-variant-numeric: tabular-nums;
  padding-bottom: env(safe-area-inset-bottom, 0px); }
.wrap { padding-inline: clamp(12px, 2vw, 32px); }
button { font: inherit; color: inherit; }
button:focus-visible, select:focus-visible, th:focus-visible { outline: 2px solid var(--mint); outline-offset: 2px; }

/* header */
header { padding-top: calc(env(safe-area-inset-top, 0px) + 22px); }
.brand { display: flex; align-items: center; gap: 12px; }
.brand .logo { width: 44px; height: 44px; border-radius: 12px; background: var(--panel-2); display: grid; place-items: center; font-size: 26px; }
.brand h1 { margin: 0; font: 800 26px/1.1 var(--head); letter-spacing: -0.01em; }
.brand p { margin: 2px 0 0; color: var(--muted); font-size: 13px; }

/* avatars */
.av { --s: 30px; width: var(--s); height: var(--s); flex: none; border-radius: 50%; background: var(--panel-2); color: var(--muted);
  display: inline-grid; place-items: center; overflow: hidden; position: relative; font: 700 calc(var(--s) * 0.42)/1 var(--head); vertical-align: middle; }
.av img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.who { display: inline-flex; align-items: center; gap: 9px; font-weight: 600; }

/* tabs */
nav { position: sticky; top: 0; z-index: 10; background: var(--bg); margin-top: 18px; border-bottom: 1px solid var(--line); }
.tabs { display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none; }
.tabs::-webkit-scrollbar { display: none; }
.tabs button { flex: none; background: none; border: 0; cursor: pointer; padding: 14px 12px 12px; color: var(--muted);
  font: 600 15px/1 var(--head); border-bottom: 3px solid transparent; }
.tabs button[aria-selected="true"] { color: var(--text); border-bottom-color: var(--mint); }

main { padding-block: 22px 60px; }
section[hidden] { display: none; }
section { scroll-margin-top: 60px; }

/* cards */
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 16px; margin-top: 16px; min-width: 0; }
.card:first-child { margin-top: 0; }
.card h2 { margin: 0 0 6px; font: 700 18px/1.25 var(--head); }
.note { color: var(--muted); font-size: 13px; margin: 4px 0 12px; max-width: 70ch; }
.cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 0 16px; }
.cols > .card { margin-top: 16px; }
.cols > .stack > .card { margin-top: 16px; }
@media (max-width: 420px) { .cols { grid-template-columns: 1fr; } }

/* tables */
.scroll { overflow-x: auto; margin: 0 -16px; padding: 0 16px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { padding: 9px 10px; text-align: right; white-space: nowrap; border-bottom: 1px solid var(--line); }
th { color: var(--muted); font: 600 12px/1.2 var(--head); cursor: pointer; user-select: none; }
th.nosort { cursor: default; }
th[aria-sort="descending"]::after { content: " \2193"; }
th[aria-sort="ascending"]::after { content: " \2191"; }
tr:last-child td { border-bottom: 0; }
th.l, td.l { text-align: left; }
td.wrap { white-space: normal; min-width: 160px; }
th.c, td.c { text-align: center; }
td.stick, th.stick { position: sticky; left: 0; background: var(--panel); z-index: 1; }
tr.cut td { border-bottom: 2px dashed var(--mint); }
.mint { color: var(--mint); } .pink { color: var(--pink); } .gold { color: var(--gold); } .muted { color: var(--muted); }
.b { font-weight: 700; }

/* week picker */
.wkpick { display: flex; align-items: center; justify-content: space-between; margin: 4px 0 6px; }
.wkpick h3 { margin: 0; font: 700 18px/1 var(--head); color: var(--muted); }
.wkpick .ctl { display: flex; align-items: center; gap: 6px; }
.wkpick button { background: none; border: 0; color: var(--mint); cursor: pointer; font: 700 18px/1 var(--head); padding: 6px 8px; }
.wkpick button:disabled { color: var(--line); cursor: default; }
.wkpick .lab { font: 700 16px/1 var(--head); color: var(--mint); min-width: 74px; text-align: center; }

/* matchup cards */
.mlist { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }
.mu { background: var(--bg); border: 1px solid var(--line); border-radius: 12px; padding: 4px 12px; }
.mu .t { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 0; }
.mu .t + .t { border-top: 1px solid var(--line); }
.mu .s { font: 700 16px/1 var(--head); color: var(--muted); }
.mu .t.won .s { color: var(--mint); }
.tag.playoff { background: rgba(255, 205, 60, 0.14); color: var(--gold); }
.tag.toilet_bowl { background: rgba(255, 92, 132, 0.14); color: var(--pink); }
.mwrap { display: flex; flex-direction: column; }

/* record cards */
.rgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 10px; }
.rec { background: var(--bg); border: 1px solid var(--line); border-radius: 14px; padding: 14px; }
.rec h4 { margin: 0 0 10px; font: 600 13px/1.2 var(--head); color: var(--muted); }
.rec .lv { font: 800 30px/1 var(--head); }
.rec .lh { margin-top: 8px; }
.rec .ld { color: var(--muted); font-size: 13px; margin-top: 4px; }
.rec ol { list-style: none; margin: 12px 0 0; padding: 10px 0 0; border-top: 1px solid var(--line); font-size: 13px; }
.rec li { display: grid; grid-template-columns: 18px 1fr auto; gap: 6px; padding: 3px 0; }
.rec li .d { grid-column: 2 / 4; color: var(--muted); font-size: 12px; margin-top: -2px; }
.rec .empty { color: var(--muted); margin: 0; }
h3.grp { font: 700 18px/1 var(--head); margin: 26px 0 12px; }

/* season pills */
.spick { display: flex; gap: 8px; flex-wrap: wrap; margin: 4px 0 4px; }
.spick button { background: var(--panel); border: 1px solid var(--line); border-radius: 999px; padding: 8px 16px; cursor: pointer; font: 700 14px/1 var(--head); color: var(--muted); }
.spick button[aria-pressed="true"] { background: var(--mint); color: var(--bg); border-color: var(--mint); }
.results { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.results .r { background: var(--bg); border: 1px solid var(--line); border-radius: 14px; padding: 12px; }
.results .k { font: 600 13px/1 var(--head); color: var(--muted); margin-bottom: 8px; }

/* score grid, finishes, h2h */
.grid td { text-align: center; padding: 8px 7px; }
.grid td.l, .grid th.l { text-align: left; }
.grid td.hi { color: var(--gold); font-weight: 700; }
.grid td.lo { color: var(--pink); }
td.h2w { background: rgba(46, 230, 197, 0.12); }
td.h2l { background: rgba(255, 92, 132, 0.12); }
td.f1 { color: var(--gold); font-weight: 700; }
td.fT { color: var(--pink); font-weight: 700; }
td.fP { color: var(--mint); }

/* draft board and position chips */
.chip { display: inline-block; min-width: 30px; text-align: center; border-radius: 6px; padding: 3px 5px; font: 700 10px/1 var(--head); color: #10142a; background: var(--other); }
.chip.QB { background: var(--qb); } .chip.RB { background: var(--rb); } .chip.WR { background: var(--wr); } .chip.TE { background: var(--te); }
.board td { text-align: left; vertical-align: top; padding: 4px; border: 0; }
.board th { text-align: left; }
.bp { border-radius: 8px; padding: 6px 7px; min-width: 112px; color: #10142a; background: var(--other); }
.bp.QB { background: var(--qb); } .bp.RB { background: var(--rb); } .bp.WR { background: var(--wr); } .bp.TE { background: var(--te); }
.bp .pn { font: 700 12px/1.2 var(--head); white-space: normal; }
.bp .pm { font-size: 11px; opacity: 0.75; }
.bp .k { float: right; font: 800 10px/1 var(--head); background: #10142a; color: var(--gold); border-radius: 4px; padding: 2px 4px; }

/* power */
.bar { display: inline-block; width: 70px; height: 6px; border-radius: 3px; background: var(--panel-2); vertical-align: middle; margin-left: 8px; overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--mint); border-radius: 3px; }
.spark { vertical-align: middle; }
.mv { font: 700 12px/1 var(--head); }

/* brackets */
.bracket { display: flex; gap: 12px; overflow-x: auto; padding-bottom: 4px; }
.bracket .rd { flex: 1 0 250px; display: flex; flex-direction: column; gap: 10px; }
.bracket .rd h4 { margin: 0; font: 600 13px/1.2 var(--head); color: var(--muted); }
.bg { background: var(--bg); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }
.bg .gn { font: 600 11px/1 var(--head); color: var(--muted); padding: 8px 10px 0; }
.bg .t { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 8px 10px; }
.bg .t + .t { border-top: 1px solid var(--line); }
.bg .t.won .sc { color: var(--mint); font-weight: 700; }
.bg .sc { font: 600 14px/1 var(--head); color: var(--muted); }

/* newsletter */
.issue { max-width: none; }
.issue h1 { font: 800 30px/1.15 var(--head); margin: 6px 0 4px; }
.issue h1 + p em { color: var(--mint); font-style: normal; font-weight: 600; font-size: 17px; }
.issue h2 { font: 700 21px/1.2 var(--head); margin: 28px 0 10px; padding-top: 18px; border-top: 1px solid var(--line); }
.issue h3 { font: 700 17px/1.2 var(--head); margin: 20px 0 8px; color: var(--gold); }
.issue p, .issue li { font-size: 16px; line-height: 1.6; max-width: 90ch; }
.issue ul { padding-left: 20px; }
.issue strong { color: var(--text); }
.issue table { width: auto; min-width: 50%; margin: 6px 0 4px; }
.issue th { cursor: default; }
.issue td, .issue th { text-align: left; }
.issue .tblwrap { overflow-x: auto; }

select { background: var(--panel-2); color: var(--text); border: 1px solid var(--line); border-radius: 10px; padding: 8px 10px; font: 600 14px var(--head); }
.row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
footer { color: var(--muted); font-size: 13px; padding-block: 0 40px; }
</style>
</head>
<body>
<header class="wrap">
  <div class="brand"><div class="logo">🦃</div><div><h1>__LEAGUE__</h1><p>Record Book</p></div></div>
</header>
<nav><div class="wrap tabs" role="tablist" id="tabs"></div></nav>
<main class="wrap">
  <section id="standings"></section>
  <section id="newsletter" hidden></section>
  <section id="power" hidden></section>
  <section id="records" hidden></section>
  <section id="managers" hidden></section>
  <section id="seasons" hidden></section>
  <section id="keepers" hidden></section>
</main>
<footer class="wrap" id="footer"></footer>

<script type="application/json" id="data">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById("data").textContent);
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const f2 = (n) => (n == null ? "" : Number(n).toFixed(2));
const f1 = (n) => (n == null ? "" : Number(n).toFixed(1));
const pct = (n) => (n == null ? "" : (n * 100).toFixed(1) + "%");
const pct0 = (n) => (n == null ? "" : n >= 0.995 && n < 1 ? ">99%" : n > 0 && n < 0.005 ? "<1%" : Math.round(n * 100) + "%");
const signed = (n, d = 1) => (n > 0 ? "+" : "") + Number(n).toFixed(d);
const ord = (n) => n + (["th", "st", "nd", "rd"][(n % 100 - 20) % 10] || ["th", "st", "nd", "rd"][n % 100] || "th");
const AV = D.avatars || {};
const av = (name, s = 30) => `<span class="av" style="--s:${s}px">${esc((name || "?").charAt(0).toUpperCase())}${
  AV[name] ? `<img src="${esc(AV[name])}" alt="" loading="lazy" onerror="this.remove()">` : ""}</span>`;
const who = (name, s = 28) => `<span class="who">${av(name, s)}<span>${esc(name)}</span></span>`;
const card = (title, body) => `<div class="card"><h2>${title}</h2>${body}</div>`;
const tag = (type, label) => type && type !== "regular" ? `<span class="tag ${type}">${esc(label || (type === "playoff" ? "Playoffs" : "Toilet Bowl"))}</span>` : "";
const when = (r) => `${r.season} wk ${r.week}`;
const chip = (pos) => `<span class="chip ${esc(pos || "")}">${esc(pos || "?")}</span>`;
const CUR = (D.seasons || [])[0];

/* ---------- sortable table helper ---------- */
let tid = 0;
function table(cols, rows, opt = {}) {
  // cols: [label, fn(row) -> [html, sortValue], cls]
  const id = "t" + (++tid);
  const state = { col: -1, dir: -1 };
  const draw = () => {
    const body = rows.slice();
    if (state.col >= 0) body.sort((a, b) => {
      const x = cols[state.col][1](a)[1], y = cols[state.col][1](b)[1];
      return ((x ?? -1e9) > (y ?? -1e9) ? 1 : (x ?? -1e9) < (y ?? -1e9) ? -1 : 0) * state.dir;
    });
    const el = $(id);
    el.innerHTML = `<thead><tr>${cols.map(([l, , c], i) => `<th tabindex="0" class="${c || ""}" data-i="${i}" ${i === state.col ? `aria-sort="${state.dir < 0 ? "descending" : "ascending"}"` : ""}>${l}</th>`).join("")}</tr></thead>
      <tbody>${body.map((r, ri) => `<tr class="${opt.rowClass ? opt.rowClass(r, ri, state.col < 0) : ""}">${cols.map(([, fn, c]) => `<td class="${c || ""}">${fn(r)[0]}</td>`).join("")}</tr>`).join("")}</tbody>`;
  };
  setTimeout(() => {
    const el = $(id); if (!el) return;
    const go = (i) => { state.dir = i === state.col ? -state.dir : -1; state.col = i; draw(); };
    el.addEventListener("click", (e) => { const th = e.target.closest("th"); if (th) go(+th.dataset.i); });
    el.addEventListener("keydown", (e) => { const th = e.target.closest("th"); if (th && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); go(+th.dataset.i); } });
    draw();
  });
  return `<div class="scroll"><table id="${id}"></table></div>`;
}

/* ---------- small pieces ---------- */
function spark(vals) {
  const v = (vals || []).filter((x) => x != null);
  if (!v.length) return "";
  const mx = Math.max(...v), mn = Math.min(...v) * 0.85, w = 6, gap = 2, h = 22;
  return `<svg class="spark" width="${v.length * (w + gap)}" height="${h}" aria-hidden="true">${v.map((x, i) => {
    const bh = Math.max(2, ((x - mn) / (mx - mn || 1)) * h);
    return `<rect x="${i * (w + gap)}" y="${h - bh}" width="${w}" height="${bh}" rx="1.5" fill="${x === mx ? "var(--gold)" : "var(--mint)"}"/>`;
  }).join("")}</svg>`;
}
function matchCard(m) {
  const t = (n, sc, won) => `<div class="t ${won ? "won" : ""}">${who(n, 28)}<span class="s">${f2(sc)}</span></div>`;
  return `<div class="mwrap">${tag(m.type, m.round)}<div class="mu">${t(m.winner, m.winner_points, !m.tie)}${t(m.loser, m.loser_points, false)}</div></div>`;
}
function weekPicker(id, weeks, start, render, title = "") {
  let i = Math.max(0, weeks.indexOf(start));
  const draw = () => {
    const el = $(id); if (!el) return;
    el.innerHTML = `<div class="wkpick"><h3>${title}</h3><div class="ctl"><button aria-label="Previous week" ${i <= 0 ? "disabled" : ""} data-d="-1">&#8249;</button><span class="lab">Week ${weeks[i]}</span><button aria-label="Next week" ${i >= weeks.length - 1 ? "disabled" : ""} data-d="1">&#8250;</button></div></div><div>${render(weeks[i])}</div>`;
    el.querySelectorAll("[data-d]").forEach((b) => b.onclick = () => { i += +b.dataset.d; draw(); });
  };
  setTimeout(draw);
  return `<div id="${id}"></div>`;
}

/* ---------- tabs ---------- */
const TABS = [["standings", "Standings"], ["newsletter", "Newsletter"], ["power", "Power"], ["records", "Records"], ["managers", "Managers"], ["seasons", "Seasons"], ["keepers", "Keepers"]];
$("tabs").innerHTML = TABS.map(([id, l]) => `<button role="tab" data-tab="${id}" aria-controls="${id}">${l}</button>`).join("");
function show(id) {
  const [base, issue] = String(id).split("/");
  id = base;
  if (issue && window.openIssue) openIssue(issue);
  if (!TABS.some(([t]) => t === id)) id = "standings";
  TABS.forEach(([t]) => $(t).hidden = t !== id);
  document.querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === id));
}
$("tabs").addEventListener("click", (e) => { const b = e.target.closest("[data-tab]"); if (b) { history.replaceState(null, "", "#" + b.dataset.tab); show(b.dataset.tab); } });

/* ================= STANDINGS ================= */
(function () {
  if (!CUR) return;
  let h = "";
  const odds = D.playoff_odds || {}, hasOdds = Object.keys(odds).length > 0, cut = CUR.playoff_teams || 6;
  const streak = (D.streaks && D.streaks.current) || {};
  const cols = [
    ["Seed", (r) => [r.seed, -r.seed], "c"],
    ["Manager", (r) => [who(r.manager), r.manager], "l stick"],
    ["Record", (r) => [r.record, r.win_pct + r.pf / 1e6]],
    ["PF", (r) => [f2(r.pf), r.pf]],
    ["PA", (r) => [f2(r.pa), r.pa]],
    ["Diff", (r) => [`<span class="${r.diff >= 0 ? "mint" : "pink"}">${signed(r.diff, 1)}</span>`, r.diff]],
    ["All-play", (r) => [r.all_play, r.all_play_pct]],
    ["Luck", (r) => [`<span class="${r.luck > 0 ? "mint" : r.luck < 0 ? "pink" : ""}">${signed(r.luck)}</span>`, r.luck]],
    ["Lineup %", (r) => [pct(r.lineup_efficiency), r.lineup_efficiency]],
    ["Streak", (r) => [streak[r.manager] || "", streak[r.manager] || ""]],
  ];
  if (hasOdds) cols.push(
    ["Playoffs", (r) => { const o = odds[r.manager]; return [o ? `<b class="${o.make >= 0.5 ? "mint" : "pink"}">${pct0(o.make)}</b>` : "", o ? o.make : -1]; }],
    ["Bye", (r) => { const o = odds[r.manager]; return [o && o.bye != null ? pct0(o.bye) : "", o ? o.bye : -1]; }],
    ["#1 seed", (r) => { const o = odds[r.manager]; return [o ? pct0(o.first) : "", o ? o.first : -1]; }]);
  h += card(`${CUR.season} standings and playoff picture`,
    `<p class="note">Seeded on record, then points for. The top ${cut} make the playoffs; the dashed line is the cut.${hasOdds ? " Odds come from simulating the rest of the regular season 3,000 times." : ""} All-play is your record if you played every team every week, and luck is how many more wins you have than that predicts.</p>` +
    table(cols, CUR.standings, { rowClass: (r, i, natural) => natural && r.seed === cut ? "cut" : "" }));

  if (CUR.matchups.length) {
    const weeks = [...new Set(CUR.matchups.map((m) => m.week))];
    h += card(`${CUR.season} scoreboard`, weekPicker("cur-wk", weeks, weeks[weeks.length - 1], (w) =>
      `<div class="mlist">${CUR.matchups.filter((m) => m.week === w).map(matchCard).join("")}</div>`));
  }
  h += `<div class="cols">${highScores(CUR)}${prizeCard(CUR)}</div>`;
  $("standings").innerHTML = h;
})();

function highScores(S) {
  const note = S.weekly_prize ? `$${S.weekly_prize} a week for the top score, regular season only. A tie splits it.` : `Regular season. There was no weekly prize in ${S.season}.`;
  return card("Weekly high score", `<p class="note">${note}</p>` +
    `<div class="scroll"><table><thead><tr><th class="c nosort">Week</th><th class="l nosort">Manager</th><th class="nosort">Score</th></tr></thead><tbody>${
      S.weekly_high_scores.map((x) => `<tr><td class="c">${x.week}</td><td class="l">${x.managers.map((m) => who(m, 24)).join(" ")}</td><td class="gold b">${f2(x.points)}</td></tr>`).join("")
    }</tbody></table></div>`);
}
function prizeCard(S) {
  if (!S.weekly_prize) return "";
  return card("Prize tally", S.prize_tally.length ? `<div class="scroll"><table><thead><tr><th class="l nosort">Manager</th><th class="nosort">Weeks</th><th class="nosort">Won</th></tr></thead><tbody>${
    S.prize_tally.map((x) => `<tr><td class="l">${who(x.manager, 24)}</td><td>${+x.weeks.toFixed(2)}</td><td class="mint b">$${x.dollars % 1 ? x.dollars.toFixed(2) : x.dollars}</td></tr>`).join("")
  }</tbody></table></div>` : `<p class="note">No weeks played yet.</p>`);
}

/* ================= NEWSLETTER ================= */
(function () {
  const N = D.newsletters || [];
  const key = (i) => `${i.season}-${i.week}`;
  if (!N.length) { $("newsletter").innerHTML = card("Newsletter", `<p class="note">No issues published yet.</p>`); return; }
  $("newsletter").innerHTML = `<div class="card"><div class="row"><label for="nl-pick" class="muted">Issue</label><select id="nl-pick">${
    N.map((i) => `<option value="${key(i)}">${i.season} ${esc(i.title)}</option>`).join("")}</select>
    <a id="nl-link" class="muted" style="margin-left:auto;font-size:13px">Link to this issue</a></div><article class="issue" id="nl-body"></article></div>`;
  window.openIssue = (k) => {
    const i = N.find((x) => key(x) === k) || N[0];
    $("nl-pick").value = key(i);
    $("nl-body").innerHTML = i.html.replace(/<table>/g, '<div class="tblwrap"><table>').replace(/<\/table>/g, "</table></div>");
    $("nl-link").href = "#newsletter/" + key(i);
  };
  $("nl-pick").onchange = (e) => { history.replaceState(null, "", "#newsletter/" + e.target.value); openIssue(e.target.value); };
  openIssue(key(N[0]));
})();

/* ================= POWER ================= */
(function () {
  const P = D.power || [];
  if (!P.length) { $("power").innerHTML = card("Power rankings", `<p class="note">Power rankings start after week 1.</p>`); return; }
  const W = D.config.power_weights, top = P[0].power;
  $("power").innerHTML = card(`Week ${CUR.weeks[CUR.weeks.length - 1]} power rankings`,
    `<p class="note">Each input is scored against the league leader, then weighted: points per game ${W.ppg}, last three games ${W.last3}, win % ${W.win}, all-play % ${W.all_play}. The trend shows each week's score, with the best week in gold.</p>` +
    table([
      ["#", (r) => [`<b>${r.rank}</b>`, -r.rank], "c"],
      ["", (r) => [r.move > 0 ? `<span class="mv mint">&#9650;${r.move}</span>` : r.move < 0 ? `<span class="mv pink">&#9660;${-r.move}</span>` : `<span class="muted">&middot;</span>`, r.move], "c"],
      ["Manager", (r) => [who(r.manager), r.manager], "l stick"],
      ["Record", (r) => [r.record, r.win_pct]],
      ["Power", (r) => [`<b>${f1(r.power)}</b><span class="bar"><i style="width:${(r.power / top) * 100}%"></i></span>`, r.power]],
      ["Trend", (r) => [spark(r.scores), 0], "l"],
      ["PPG", (r) => [f2(r.ppg), r.ppg]],
      ["Last 3", (r) => [f2(r.last3), r.last3]],
      ["All-play", (r) => [pct(r.all_play_pct), r.all_play_pct]],
    ], P));
})();

/* ================= RECORDS ================= */
(function () {
  const gameRec = (r) => ({ v: f2(r.points), h: r.manager, d: `vs ${esc(r.opponent)} (${f2(r.opp_points)}), ${when(r)} ${tag(r.type)}` });
  const matchRec = (k) => (r) => ({ v: f2(r[k]), h: r.winner, d: `over ${esc(r.loser)}, ${f2(r.winner_points)} to ${f2(r.loser_points)}, ${when(r)} ${tag(r.type)}` });
  const seasonRec = (fn) => (r) => ({ v: fn(r), h: r.manager, d: `${r.season}, ${r.record}` });
  const playerRec = (bench) => (r) => ({ v: f2(r.points), h: r.manager, d: `${esc(r.player)}${r.position ? " " + chip(r.position) : ""} ${bench ? "on the bench" : ""}, ${when(r)}` });
  const streakRec = (r) => ({ v: r.length, h: r.manager, d: `${r.from.replace(" W", " wk ")} to ${r.to.replace(" W", " wk ")}` });
  const G = [
    ["Single game", "single_game", [
      ["highest_score", "Highest score", gameRec], ["lowest_score", "Lowest score", gameRec],
      ["highest_score_in_loss", "Highest score in a loss", gameRec], ["lowest_score_in_win", "Lowest score in a win", gameRec],
      ["biggest_blowout", "Biggest blowout", matchRec("margin")], ["closest_game", "Closest game", matchRec("margin")],
      ["highest_combined", "Highest-scoring matchup", matchRec("combined")], ["lowest_combined", "Lowest-scoring matchup", matchRec("combined")]]],
    ["Lineup decisions", "single_game", [
      ["most_points_left_on_bench", "Most points left on the bench", (r) => ({ v: f2(r.left_on_bench), h: r.manager, d: `Scored ${f2(r.points)} of a possible ${f2(r.optimal)}, ${when(r)}` })],
      ["losses_optimal_lineup_would_have_won", "Lost with a winner on the bench", (r) => ({ v: f2(r.optimal), h: r.manager, d: `Lost ${f2(r.points)} to ${f2(r.opp_points)} vs ${esc(r.opponent)}, ${when(r)}` })]]],
    ["Season", "season", [
      ["most_points_for", "Most points in a season", seasonRec((r) => f2(r.points_for))],
      ["fewest_points_for", "Fewest points in a season", seasonRec((r) => f2(r.points_for))],
      ["most_points_against", "Most points against", seasonRec((r) => f2(r.points_against))],
      ["best_record", "Best record", seasonRec((r) => r.record)], ["worst_record", "Worst record", seasonRec((r) => r.record)],
      ["luckiest", "Luckiest season", seasonRec((r) => signed(r.luck) + " W")], ["unluckiest", "Unluckiest season", seasonRec((r) => signed(r.luck) + " W")],
      ["best_lineup_efficiency", "Best lineup setter", seasonRec((r) => pct(r.lineup_efficiency))],
      ["worst_lineup_efficiency", "Worst lineup setter", seasonRec((r) => pct(r.lineup_efficiency))],
      ["most_weekly_high_scores", "Most weekly high scores", seasonRec((r) => r.weekly_high_scores)]]],
    ["Players", "players", [
      ["highest_starter_score", "Best player game", playerRec(false)], ["highest_benched_score", "Best game left on the bench", playerRec(true)]]],
    ["Streaks", "streaks", [["longest_win_streak", "Longest win streak", streakRec], ["longest_loss_streak", "Longest losing streak", streakRec]]],
    ["Waivers", "transactions", [
      ["biggest_faab_bids", "Biggest FAAB bid", (r) => ({ v: "$" + r.bid, h: r.manager, d: `${esc(r.player)}, ${r.season} wk ${r.week}` })],
      ["most_faab_spent_season", "Most FAAB spent in a season", (r) => ({ v: "$" + r.spent, h: r.manager, d: r.season })],
      ["most_pickups_season", "Most pickups in a season", (r) => ({ v: r.pickups, h: r.manager, d: r.season })]]],
  ];
  $("records").innerHTML = `<p class="note">Game records count regular season, playoff and Toilet Bowl games. Season records use completed regular seasons only.</p>` +
    G.map(([title, src, list]) => `<h3 class="grp">${title}</h3><div class="rgrid">${list.map(([k, label, fmt]) => {
      const L = (((D[src] || {})[k]) || []).slice(0, 5).map(fmt);
      if (!L.length) return `<div class="rec"><h4>${label}</h4><p class="empty">No entries yet.</p></div>`;
      const [a, ...rest] = L;
      return `<div class="rec"><h4>${label}</h4><div class="lv">${a.v}</div><div class="lh">${who(a.h, 26)}</div><div class="ld">${a.d}</div>${
        rest.length ? `<ol>${rest.map((x, i) => `<li><span class="muted">${i + 2}</span><span>${esc(x.h)}</span><span>${x.v}</span><span class="d">${x.d}</span></li>`).join("")}</ol>` : ""}</div>`;
    }).join("")}</div>`).join("");
})();

/* ================= MANAGERS ================= */
(function () {
  const M = D.managers || [];
  let h = card("All-time", `<p class="note">Regular season unless the column says playoffs. Tap a column to sort.</p>` + table([
    ["Manager", (m) => [who(m.manager), m.manager], "l stick"],
    ["Seasons", (m) => [m.seasons, m.seasons]],
    ["Record", (m) => [m.record, m.win_pct]],
    ["Win %", (m) => [pct(m.win_pct), m.win_pct]],
    ["PF", (m) => [f2(m.points_for), m.points_for]],
    ["PPG", (m) => [f2(m.ppg), m.ppg]],
    ["All-play %", (m) => [pct(m.all_play_pct), m.all_play_pct]],
    ["High", (m) => [f2(m.career_high), m.career_high]],
    ["Low", (m) => [f2(m.career_low), m.career_low]],
    ["Avg finish", (m) => [m.avg_finish ? f1(m.avg_finish) : "", m.avg_finish ? -m.avg_finish : -99]],
    ["Playoffs", (m) => [m.playoff_appearances, m.playoff_appearances]],
    ["Titles", (m) => [m.championships ? `<b class="gold">${m.championships}</b>` : 0, m.championships]],
    ["Runner-up", (m) => [m.runner_ups, m.runner_ups]],
    ["Turkeys", (m) => [m.turkeys ? `<b class="pink">${m.turkeys}</b>` : 0, m.turkeys]],
    ["High scores", (m) => [m.weekly_high_scores, m.weekly_high_scores]],
    ["Trades", (m) => [m.trades, m.trades]],
  ], M));

  const F = D.finishes || { seasons: [], rows: [] };
  if (F.seasons.length) h += card("Where everyone finished", `<p class="note">Final place each season. Gold is a title, pink is the turkey, mint made the playoffs.</p>` +
    `<div class="scroll"><table class="grid"><thead><tr><th class="l stick nosort">Manager</th>${F.seasons.map((s) => `<th class="c nosort">${s}</th>`).join("")}<th class="c nosort">Avg</th></tr></thead><tbody>${
      F.rows.map((r) => `<tr><td class="l stick">${who(r.manager, 24)}</td>${F.seasons.map((s) => {
        const x = r.seasons[s]; if (!x) return `<td class="muted">&middot;</td>`;
        return `<td class="${x.title ? "f1" : x.turkey ? "fT" : x.playoffs ? "fP" : ""}">${x.title ? "🏆 " : x.turkey ? "🦃 " : ""}${ord(x.place)}</td>`;
      }).join("")}<td class="b">${r.avg ? f1(r.avg) : ""}</td></tr>`).join("")}</tbody></table></div>`);

  h += `<div class="cols">`;
  h += card("Postseason", table([
    ["Manager", (m) => [who(m.manager, 24), m.manager], "l stick"],
    ["G", (m) => [m.playoff_games, m.playoff_games]],
    ["W-L", (m) => [`${m.playoff_wins}-${m.playoff_games - m.playoff_wins}`, m.playoff_wins]],
    ["Win %", (m) => [m.playoff_games ? pct(m.playoff_win_pct) : "", m.playoff_win_pct ?? -1]],
    ["PPG", (m) => [m.playoff_ppg ? f2(m.playoff_ppg) : "", m.playoff_ppg ?? -1]],
    ["🏆", (m) => [m.championships || "", m.championships]],
    ["🦃", (m) => [m.turkeys || "", m.turkeys]],
  ], M.filter((m) => m.playoff_games || m.turkeys).sort((a, b) => b.championships - a.championships || b.playoff_wins - a.playoff_wins)));
  h += card("Longest runs", `<p class="note">Consecutive wins and losses across every season, playoffs included.</p>` + table([
    ["Manager", (r) => [who(r.manager, 24), r.manager], "l stick"],
    ["Games", (r) => [r.games, r.games]],
    ["Best", (r) => [`<span class="mint b">${r.best}W</span>`, r.best]],
    ["Worst", (r) => [`<span class="pink b">${r.worst}L</span>`, r.worst]],
    ["Now", (r) => [r.now, r.now]],
  ], D.runs || []));
  h += `</div>`;

  h += card("Rivalries", `<p class="note">The pairs who have played each other most, and how one-sided it has been.</p>` + table([
    ["Matchup", (p) => [`${esc(p.a)} vs ${esc(p.b)}`, p.a], "l"],
    ["Games", (p) => [p.games, p.games]],
    ["Series", (p) => [`${p.a_wins}-${p.b_wins}${p.ties ? "-" + p.ties : ""}`, Math.abs(p.a_wins - p.b_wins)]],
    ["Avg margin", (p) => [f2(p.avg_margin), p.avg_margin]],
    ["Biggest win", (p) => [`${esc(p.biggest.winner)} by ${f2(p.biggest.margin)} <span class="muted">(${p.biggest.season} wk ${p.biggest.week})</span>`, p.biggest.margin], "l"],
  ], D.rivals || []));

  const names = Object.keys(D.head_to_head || {}).sort((a, b) => a.localeCompare(b));
  h += card("Head-to-head", `<p class="note">Read across: each row is that manager's record against the column's manager, every game type included.</p>` +
    `<div class="scroll"><table class="grid"><thead><tr><th class="stick nosort"></th>${names.map((n) => `<th class="c nosort" title="${esc(n)}">${av(n, 26)}</th>`).join("")}</tr></thead><tbody>${
      names.map((a) => `<tr><td class="l stick">${who(a, 24)}</td>${names.map((b) => {
        if (a === b) return `<td class="muted">&middot;</td>`;
        const v = (D.head_to_head[a] || {})[b]; if (!v) return "<td></td>";
        return `<td class="${v.w > v.l ? "h2w" : v.l > v.w ? "h2l" : ""}">${v.w}-${v.l}${v.t ? "-" + v.t : ""}</td>`;
      }).join("")}</tr>`).join("")}</tbody></table></div>` +
    `<div class="row" style="margin-top:18px"><label for="mgr-pick" class="muted">One manager's series</label><select id="mgr-pick">${names.map((n) => `<option>${esc(n)}</option>`).join("")}</select></div><div id="mgr-h2h"></div>`);
  $("managers").innerHTML = h;
  const one = (name) => {
    const rows = Object.entries(D.head_to_head[name] || {}).map(([opp, v]) => ({ opp, ...v })).sort((a, b) => a.opp.localeCompare(b.opp));
    $("mgr-h2h").innerHTML = table([
      ["Opponent", (r) => [who(r.opp, 24), r.opp], "l stick"],
      ["Record", (r) => [`${r.w}-${r.l}${r.t ? "-" + r.t : ""}`, r.w - r.l]],
      ["PF", (r) => [f2(r.pf), r.pf]], ["PA", (r) => [f2(r.pa), r.pa]],
      ["Margin", (r) => { const d = r.pf - r.pa; return [`<span class="${d >= 0 ? "mint" : "pink"}">${signed(d)}</span>`, d]; }],
    ], rows);
  };
  if (names.length) { $("mgr-pick").onchange = (e) => one(e.target.value); one(names[0]); }
})();

/* ================= SEASONS ================= */
function renderSeason(S) {
  let h = "";
  if (S.complete) {
    const r = (k, n, cls) => n ? `<div class="r"><div class="k">${k}</div><div class="who ${cls || ""}">${av(n, 36)}<span>${esc(n)}</span></div></div>` : "";
    h += card(`${S.season} results`, `<div class="results">${r("Champion", S.champion, "gold")}${r("Runner-up", S.runner_up)}${r("Third place", S.third)}${r("Wore the turkey", S.turkey, "pink")}</div>`);
  }
  h += card(S.complete ? "Final standings" : "Standings", table([
    [S.complete ? "Place" : "Seed", (r) => [S.complete ? ord(r.place) : r.seed, -(S.complete ? r.place : r.seed)], "c"],
    ["Manager", (r) => [who(r.manager), r.manager], "l stick"],
    ...(S.complete ? [["Seed", (r) => [r.seed, -r.seed], "c"]] : []),
    ["Record", (r) => [r.record, r.win_pct + r.pf / 1e6]],
    ["PF", (r) => [f2(r.pf), r.pf]], ["PA", (r) => [f2(r.pa), r.pa]],
    ["PPG", (r) => [f2(r.ppg), r.ppg]], ["High", (r) => [f2(r.high), r.high]], ["Low", (r) => [f2(r.low), r.low]],
    ["Std dev", (r) => [f1(r.sd), r.sd]],
    ["All-play", (r) => [r.all_play, r.all_play_pct]],
    ["Luck", (r) => [`<span class="${r.luck > 0 ? "mint" : r.luck < 0 ? "pink" : ""}">${signed(r.luck)}</span>`, r.luck]],
    ["Lineup %", (r) => [pct(r.lineup_efficiency), r.lineup_efficiency]],
    ["Bench pts", (r) => [f2(r.bench_points), r.bench_points]],
  ], S.complete ? S.standings.slice().sort((a, b) => a.place - b.place) : S.standings));

  const awards = !S.awards.length ? "" : card("Awards", `<div class="scroll"><table><thead><tr><th class="l nosort">Award</th><th class="l nosort">Winner</th><th class="nosort">Value</th><th class="l nosort">Detail</th></tr></thead><tbody>${
    S.awards.map((a) => `<tr><td class="l">${esc(a.label)}</td><td class="l">${a.who === "Whole league" ? `<span class="muted">Whole league</span>` : who(a.who, 24)}</td><td class="b">${esc(a.value)}</td><td class="l muted wrap">${esc(a.detail)}</td></tr>`).join("")
  }</tbody></table></div>`);
  h += `<div class="cols">${awards}<div class="stack">${highScores(S)}${prizeCard(S)}</div></div>`;

  if (S.weeks.length) {
    const hi = {}, lo = {};
    S.weeks.forEach((w, i) => { const v = S.standings.map((r) => r.scores[i]).filter((x) => x != null); hi[i] = Math.max(...v); lo[i] = Math.min(...v); });
    h += card("Weekly scores", `<p class="note">Regular season. Gold is the week's high score, pink the low.</p><div class="scroll"><table class="grid"><thead><tr><th class="l stick nosort">Manager</th>${
      S.weeks.map((w) => `<th class="c nosort">${w}</th>`).join("")}<th class="c nosort">Total</th></tr></thead><tbody>${
      S.standings.map((r) => `<tr><td class="l stick">${who(r.manager, 24)}</td>${r.scores.map((x, i) => `<td class="${x === hi[i] ? "hi" : x === lo[i] ? "lo" : ""}">${x == null ? "" : f2(x)}</td>`).join("")}<td class="b">${f2(r.pf)}</td></tr>`).join("")
    }</tbody></table></div>`);
  }

  ["playoff", "toilet_bowl"].forEach((b) => {
    const games = S.brackets.filter((g) => g.bracket === b && (g.t1 || g.t2));
    if (!games.length || !S.regular_complete) return;
    const rounds = [...new Set(games.map((g) => g.round))].sort((x, y) => x - y);
    h += card(b === "playoff" ? "Playoff bracket" : "Toilet Bowl", (b === "toilet_bowl" ? `<p class="note">Losers advance. The last one standing wears the turkey and picks first next year.</p>` : "") +
      `<div class="bracket">${rounds.map((r) => `<div class="rd"><h4>Week ${games.find((g) => g.round === r).week}</h4>${games.filter((g) => g.round === r).map((g) => {
        const t = (n, s) => `<div class="t ${g.winner && g.winner === n && b === "playoff" ? "won" : ""}">${n ? who(n, 24) : `<span class="muted">TBD</span>`}<span class="sc">${s == null ? "" : f2(s)}</span></div>`;
        return `<div class="bg"><div class="gn">${esc(g.name)}</div>${t(g.t1, g.s1)}${t(g.t2, g.s2)}</div>`;
      }).join("")}</div>`).join("")}</div>`);
  });

  if (S.matchups.length) {
    const weeks = [...new Set(S.matchups.map((m) => m.week))];
    h += card("Every matchup", weekPicker("s-wk-" + S.season, weeks, weeks[0], (w) => `<div class="mlist">${S.matchups.filter((m) => m.week === w).map(matchCard).join("")}</div>`));
  }
  if (S.draft) {
    const rounds = [...new Set(S.draft.picks.map((p) => p.round))].sort((a, b) => a - b);
    h += card(`${S.season} draft board`, `<p class="note">Columns follow the round one order. K marks a keeper.</p><div class="scroll"><table class="board"><thead><tr><th class="stick nosort">Rd</th>${
      S.draft.order.map((n) => `<th class="nosort">${who(n, 22)}</th>`).join("")}</tr></thead><tbody>${
      rounds.map((rd) => `<tr><td class="stick b muted">${rd}</td>${S.draft.order.map((n) => {
        const p = S.draft.picks.find((x) => x.round === rd && x.manager === n);
        return p ? `<td><div class="bp ${esc(p.position || "")}">${p.keeper ? `<span class="k">K</span>` : ""}<div class="pn">${esc(p.player)}</div><div class="pm">${esc(p.position || "")} ${esc(p.team || "")} #${p.pick}</div></div></td>` : "<td></td>";
      }).join("")}</tr>`).join("")}</tbody></table></div>`);
  }
  return h;
}
(function () {
  const list = D.seasons || [];
  $("seasons").innerHTML = `<div class="spick" role="group" aria-label="Season">${list.map((s, i) => `<button data-s="${i}" aria-pressed="${i === 0}">${s.season}</button>`).join("")}</div><div id="season-body"></div>`;
  const pick = (i) => {
    document.querySelectorAll("[data-s]").forEach((b) => b.setAttribute("aria-pressed", +b.dataset.s === i));
    $("season-body").innerHTML = renderSeason(list[i]);
  };
  document.querySelectorAll("[data-s]").forEach((b) => b.onclick = () => pick(+b.dataset.s));
  if (list.length) pick(0);
})();

/* ================= KEEPERS ================= */
(function () {
  const K = D.keepers || [];
  const mgrs = [...new Set(K.map((k) => k.manager))].sort((a, b) => a.localeCompare(b));
  let h = card(`${CUR ? Number(CUR.season) + 1 : ""} keeper costs`, `<p class="note">What each rostered player would cost to keep in next year's draft (Constitution article 7). A keeper costs one round earlier than where he was drafted, and one more round earlier for each season already kept. Undrafted pickups cost a 5th, then a 4th. Nobody can be kept into round 1, and two straight seasons is the limit. If two of your keepers land on the same round, you choose which one keeps it and the other moves up a round.</p>` +
    `<div class="row"><label for="kp" class="muted">Manager</label><select id="kp"><option value="">Everyone</option>${mgrs.map((m) => `<option>${esc(m)}</option>`).join("")}</select></div><div id="kp-body" style="margin-top:10px"></div>`);
  const DH = D.draft_history || {}, ds = Object.keys(DH).sort();
  if (ds.length) {
    const all = [...new Set(ds.flatMap((s) => DH[s]))].sort((a, b) => a.localeCompare(b));
    h += card("Draft position history", `<div class="scroll"><table class="grid"><thead><tr><th class="l stick nosort">Manager</th>${ds.map((s) => `<th class="c nosort">${s}</th>`).join("")}</tr></thead><tbody>${
      all.map((m) => `<tr><td class="l stick">${who(m, 24)}</td>${ds.map((s) => { const i = DH[s].indexOf(m); return `<td>${i < 0 ? `<span class="muted">&middot;</span>` : ord(i + 1)}</td>`; }).join("")}</tr>`).join("")
    }</tbody></table></div>`);
  }
  $("keepers").innerHTML = h;
  const draw = (m) => {
    $("kp-body").innerHTML = table([
      ["Manager", (k) => [who(k.manager, 24), k.manager], "l stick"],
      ["Player", (k) => [`${chip(k.position)} ${esc(k.player)} <span class="muted">${esc(k.team || "")}</span>`, k.player], "l"],
      ["Drafted", (k) => [k.drafted, k.drafted === "Undrafted" ? 99 : parseInt(k.drafted.slice(6))], "l"],
      ["Kept", (k) => [k.years_kept, k.years_kept]],
      ["Next cost", (k) => [k.cost ? `<b class="mint">${esc(k.status)}</b>` : `<span class="pink">${esc(k.status)}</span>`, k.cost ? -k.cost : -99], "l"],
    ], m ? K.filter((k) => k.manager === m) : K);
  };
  if ($("kp")) { $("kp").onchange = (e) => draw(e.target.value); draw(""); }
})();

show(location.hash.slice(1));
$("footer").textContent = `Updated through ${D.generated_through.season} week ${D.generated_through.week}. Stats straight from Sleeper, refreshed every Tuesday.`;
</script>
</body>
</html>
"""

data = json.dumps(records, separators=(",", ":")).replace("</", "<\\/")
html = TEMPLATE.replace("__LEAGUE__", league_name.replace("<", "&lt;")).replace("__DATA__", data)
OUT_DIR.mkdir(exist_ok=True)
(OUT_DIR / "index.html").write_text(html, encoding="utf-8")
(OUT_DIR / ".nojekyll").write_text("")
print(f"Wrote {(OUT_DIR / 'index.html').relative_to(ROOT)} ({len(html) // 1024} KB)")
