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

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__LEAGUE__ Record Book</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🦃</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@600;800&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #eef2ed;
  --surface: #ffffff;
  --ink: #1d2a23;
  --muted: #5b6a61;
  --line: #d3dcd4;
  --bronze: #8f5418;
  --red: #b3261e;
  --teal: #1d6a62;
  --win-tint: rgba(29, 106, 98, 0.14);
  --loss-tint: rgba(179, 38, 30, 0.12);
  --display: "Big Shoulders Display", "Arial Narrow", "Roboto Condensed", Impact, sans-serif;
  --body: "Source Sans 3", "Segoe UI", system-ui, -apple-system, sans-serif;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #131a16;
    --surface: #1b241f;
    --ink: #e6ece7;
    --muted: #97a69d;
    --line: #2d3a33;
    --bronze: #d99a55;
    --red: #e86a60;
    --teal: #63c2b6;
    --win-tint: rgba(99, 194, 182, 0.16);
    --loss-tint: rgba(232, 106, 96, 0.16);
    color-scheme: dark;
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font: 400 1rem/1.5 var(--body);
  font-variant-numeric: tabular-nums;
}
.wrap { max-width: 1080px; margin: 0 auto; padding-inline: 1.25rem; }

/* Hero: the champion and the turkey, side by side */
.hero { padding-block: 2.5rem 2rem; }
.league { margin: 0 0 1.5rem; font: 800 1.15rem/1 var(--display); letter-spacing: 0.02em; color: var(--muted); }
.duo { display: grid; grid-template-columns: 1.4fr 1fr; gap: 1.5rem 3rem; align-items: end; }
.duo .role { display: block; font-size: 0.95rem; color: var(--muted); margin-bottom: 0.25rem; }
.duo .who { display: block; font: 800 clamp(3.2rem, 11vw, 7.5rem)/0.85 var(--display); letter-spacing: -0.01em; }
.duo .when { display: block; margin-top: 0.5rem; color: var(--muted); }
.champ .who { color: var(--bronze); }
.turkey .who { color: var(--red); font-size: clamp(2.2rem, 7vw, 4.5rem); }
@media (max-width: 640px) { .duo { grid-template-columns: 1fr; } }

/* Tabs */
nav { position: sticky; top: 0; z-index: 5; background: var(--bg); border-bottom: 1px solid var(--line); }
.tabs { display: flex; gap: 0.25rem; overflow-x: auto; scrollbar-width: none; }
.tabs button {
  flex: none; border: 0; background: none; color: var(--muted); cursor: pointer;
  font: 600 1.05rem/1 var(--body); padding: 1rem 0.75rem 0.85rem;
  border-bottom: 3px solid transparent;
}
.tabs button[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--bronze); }
button:focus-visible, select:focus-visible, th:focus-visible { outline: 2px solid var(--teal); outline-offset: 2px; }

main { padding-block: 2.25rem 4rem; }
section[hidden] { display: none; }
section { scroll-margin-top: 4.5rem; }
h2 { font: 800 2.2rem/1 var(--display); margin: 0 0 0.35rem; }
h3 { font: 800 1.45rem/1.1 var(--display); margin: 2.25rem 0 0.9rem; }
.note { color: var(--muted); margin: 0 0 1.5rem; max-width: 65ch; }

/* Tables */
.scroll { overflow-x: auto; background: var(--surface); border: 1px solid var(--line); border-radius: 6px; }
table { border-collapse: collapse; width: 100%; font-size: 0.95rem; }
th, td { padding: 0.6rem 0.75rem; text-align: right; white-space: nowrap; border-bottom: 1px solid var(--line); }
th { font-weight: 600; color: var(--muted); cursor: pointer; user-select: none; }
th[aria-sort="descending"]::after { content: " \2193"; }
th[aria-sort="ascending"]::after { content: " \2191"; }
tr:last-child td { border-bottom: 0; }
th:first-child, td:first-child { text-align: left; position: sticky; left: 0; background: var(--surface); }
td.name { font-weight: 700; }
th.name, td.name { text-align: left; }
td.rank { color: var(--muted); }
.pos { color: var(--teal); }
.neg { color: var(--red); }

/* Records: the leader is big, the chasers are small */
.rec-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1rem; }
.rec { background: var(--surface); border: 1px solid var(--line); border-radius: 6px; padding: 1.1rem 1.2rem 1rem; }
.rec h4 { margin: 0 0 0.75rem; font-size: 1rem; font-weight: 600; color: var(--muted); }
.rec .lead-value { font: 800 2.6rem/1 var(--display); }
.rec .lead-holder { font-weight: 700; font-size: 1.1rem; margin-top: 0.35rem; }
.rec .lead-detail { color: var(--muted); font-size: 0.9rem; }
.rec ol { list-style: none; margin: 0.9rem 0 0; padding: 0.75rem 0 0; border-top: 1px solid var(--line); font-size: 0.9rem; }
.rec li { display: grid; grid-template-columns: 1.25rem 1fr auto; gap: 0.5rem; padding: 0.15rem 0; }
.rec li .n { color: var(--muted); }
.rec li .d { color: var(--muted); font-size: 0.82rem; grid-column: 2 / 4; margin-top: -0.15rem; }
.rec .empty { color: var(--muted); margin: 0; }
.tag { display: inline-block; font-size: 0.75rem; font-weight: 700; padding: 0.05rem 0.4rem; border-radius: 3px; margin-left: 0.3rem; vertical-align: 0.1em; }
.tag.playoff { color: var(--bronze); border: 1px solid var(--bronze); }
.tag.toilet_bowl { color: var(--red); border: 1px solid var(--red); }

/* Seasons */
.season { display: grid; grid-template-columns: 7rem 1fr; gap: 1.5rem; padding: 1.5rem 0; border-bottom: 1px solid var(--line); }
.season .yr { font: 800 3.2rem/0.9 var(--display); color: var(--muted); }
.season dl { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 0.9rem 1.5rem; margin: 0; }
.season dt { color: var(--muted); font-size: 0.85rem; }
.season dd { margin: 0; font-weight: 700; font-size: 1.15rem; }
.season dd.gold { color: var(--bronze); font: 800 1.9rem/1 var(--display); }
.season dd.bird { color: var(--red); font: 800 1.9rem/1 var(--display); }
@media (max-width: 640px) { .season { grid-template-columns: 1fr; gap: 0.5rem; } }

/* Head to head */
.h2h td { text-align: center; }
.h2h td.w { background: var(--win-tint); }
.h2h td.l { background: var(--loss-tint); }
.h2h td.self { color: var(--line); }
.h2h th:not(:first-child) { text-align: center; cursor: default; }
.picker { display: flex; align-items: center; gap: 0.75rem; margin: 0 0 1rem; }
select { font: 600 1rem var(--body); padding: 0.45rem 0.6rem; border: 1px solid var(--line); border-radius: 4px; background: var(--surface); color: var(--ink); }
.trophies { margin: 0 0 1rem; color: var(--muted); }

footer { color: var(--muted); font-size: 0.9rem; padding-block: 1.5rem 3rem; }
</style>
</head>
<body>
<header class="wrap hero">
  <p class="league">__LEAGUE__ Record Book</p>
  <div class="duo" id="hero"></div>
</header>
<nav><div class="wrap tabs" role="tablist" id="tabs"></div></nav>
<main class="wrap">
  <section id="standings">
    <h2>Standings</h2>
    <p class="note">All-play is your record if you played every team every week. Luck is how many more wins you have than that record would predict. Lineup % is points scored out of the most you could have scored with your roster.</p>
    <div class="scroll"><table id="standings-table"></table></div>
  </section>
  <section id="records" hidden>
    <h2>Records</h2>
    <p class="note">Game records count regular season, playoff, and toilet bowl games. Season records use completed regular seasons only.</p>
    <div id="records-body"></div>
  </section>
  <section id="managers" hidden>
    <h2>Managers</h2>
    <p class="note">All-time regular season totals. Tap a column to sort.</p>
    <div class="scroll"><table id="managers-table"></table></div>
    <h3>Head-to-head for one manager</h3>
    <div class="picker"><label for="mgr-pick">Manager</label><select id="mgr-pick"></select></div>
    <p class="trophies" id="mgr-trophies"></p>
    <div class="scroll"><table id="mgr-h2h"></table></div>
  </section>
  <section id="h2h" hidden>
    <h2>Head-to-head</h2>
    <p class="note">Read across: each row is that manager's record against the column's manager, all game types included.</p>
    <div class="scroll"><table class="h2h" id="h2h-table"></table></div>
  </section>
  <section id="seasons" hidden>
    <h2>Seasons</h2>
    <div id="seasons-body"></div>
  </section>
</main>
<footer class="wrap" id="footer"></footer>

<script type="application/json" id="data">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById("data").textContent);
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const f2 = (n) => (n == null ? "" : Number(n).toFixed(2));
const pct = (n) => (n == null ? "" : (n * 100).toFixed(1) + "%");
const signed = (n) => (n > 0 ? "+" : "") + Number(n).toFixed(1);
const when = (r) => `${r.season} week ${r.week}` + (r.type && r.type !== "regular"
  ? `<span class="tag ${r.type}">${r.type === "playoff" ? "playoffs" : "toilet bowl"}</span>` : "");
const wk = (s) => s.replace(" W", " week ");

/* ---------- hero ---------- */
const done = D.history.filter((h) => h.champion);
const last = done[done.length - 1];
$("hero").innerHTML = last
  ? `<div class="champ"><span class="role">Reigning champion</span><span class="who">${esc(last.champion)}</span><span class="when">${last.season} season</span></div>
     <div class="turkey"><span class="role">Wearing the turkey</span><span class="who">${esc(last.turkey ?? "TBD")}</span></div>`
  : `<div class="champ"><span class="role">Reigning champion</span><span class="who">TBD</span></div>`;

/* ---------- tabs ---------- */
const TABS = [["standings", "Standings"], ["records", "Records"], ["managers", "Managers"], ["h2h", "Head-to-head"], ["seasons", "Seasons"]];
$("tabs").innerHTML = TABS.map(([id, label]) => `<button role="tab" data-tab="${id}" aria-controls="${id}">${label}</button>`).join("");
function show(id) {
  if (!TABS.some(([t]) => t === id)) id = "standings";
  TABS.forEach(([t]) => { $(t).hidden = t !== id; });
  document.querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === id));
}
$("tabs").addEventListener("click", (e) => {
  const b = e.target.closest("[data-tab]");
  if (b) { history.replaceState(null, "", "#" + b.dataset.tab); show(b.dataset.tab); }
});
show(location.hash.slice(1));

/* ---------- sortable tables ---------- */
function table(el, cols, rows) {
  // cols: [label, (row) => [display html, sort value], extra class]
  let sortCol = -1, dir = -1;
  const render = () => {
    const body = rows.slice();
    if (sortCol >= 0) body.sort((a, b) => {
      const x = cols[sortCol][1](a)[1], y = cols[sortCol][1](b)[1];
      return (x > y ? 1 : x < y ? -1 : 0) * dir;
    });
    el.innerHTML = `<thead><tr>${cols.map(([l], i) =>
      `<th tabindex="0" class="${cols[i][2] || ""}" data-i="${i}" ${i === sortCol ? `aria-sort="${dir < 0 ? "descending" : "ascending"}"` : ""}>${l}</th>`).join("")}</tr></thead>
      <tbody>${body.map((r) => `<tr>${cols.map(([, fn, cls]) => `<td class="${cls || ""}">${fn(r)[0]}</td>`).join("")}</tr>`).join("")}</tbody>`;
  };
  const sortBy = (i) => { dir = i === sortCol ? -dir : -1; sortCol = i; render(); };
  el.addEventListener("click", (e) => { const th = e.target.closest("th"); if (th) sortBy(+th.dataset.i); });
  el.addEventListener("keydown", (e) => { const th = e.target.closest("th"); if (th && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); sortBy(+th.dataset.i); } });
  render();
}
const recWins = (rec) => { const [w, l, t] = rec.split("-").map(Number); return w + 0.5 * (t || 0) - l * 0.0001; };

/* ---------- standings ---------- */
const streaks = D.streaks.current || {};
table($("standings-table"), [
  ["#", (r) => [D.current_season.indexOf(r) + 1, -D.current_season.indexOf(r)], "rank"],
  ["Manager", (r) => [esc(r.manager), r.manager], "name"],
  ["Record", (r) => [r.record, r.win_pct + r.points_for / 1e6]],
  ["PF", (r) => [f2(r.points_for), r.points_for]],
  ["PA", (r) => [f2(r.points_against), r.points_against]],
  ["All-play", (r) => [r.all_play, r.all_play_pct]],
  ["Luck", (r) => [`<span class="${r.luck > 0 ? "pos" : r.luck < 0 ? "neg" : ""}">${signed(r.luck)}</span>`, r.luck]],
  ["Lineup %", (r) => [pct(r.lineup_efficiency), r.lineup_efficiency]],
  ["High scores", (r) => [r.weekly_high_scores, r.weekly_high_scores]],
  ["Streak", (r) => [streaks[r.manager] || "", streaks[r.manager] || ""]],
], D.current_season);

/* ---------- records ---------- */
const gameRec = (r) => ({ value: f2(r.points), holder: r.manager, detail: `vs ${esc(r.opponent)} (${f2(r.opp_points)}), ${when(r)}` });
const matchRec = (key) => (r) => ({ value: f2(r[key]), holder: `${r.winner} over ${r.loser}`, detail: `${f2(r.winner_points)} to ${f2(r.loser_points)}, ${when(r)}` });
const seasonRec = (val) => (r) => ({ value: val(r), holder: r.manager, detail: `${r.season}, ${r.record}` });
const playerRec = (bench) => (r) => ({ value: f2(r.points), holder: `${r.player}${r.position ? ", " + r.position : ""}`, detail: `${bench ? "On " + esc(r.manager) + "'s bench" : "For " + esc(r.manager)}, ${when(r)}` });
const streakRec = (r) => ({ value: `${r.length}`, holder: r.manager, detail: `${wk(r.from)} to ${wk(r.to)}` });

const GROUPS = [
  ["Single game", "single_game", [
    ["highest_score", "Highest score", gameRec],
    ["lowest_score", "Lowest score", gameRec],
    ["highest_score_in_loss", "Highest score in a loss", gameRec],
    ["lowest_score_in_win", "Lowest score in a win", gameRec],
    ["biggest_blowout", "Biggest blowout", matchRec("margin")],
    ["closest_game", "Closest game", matchRec("margin")],
    ["highest_combined", "Highest-scoring game", matchRec("combined")],
    ["lowest_combined", "Lowest-scoring game", matchRec("combined")],
  ]],
  ["Lineup decisions", "single_game", [
    ["most_points_left_on_bench", "Most points left on the bench", (r) => ({ value: f2(r.left_on_bench), holder: r.manager, detail: `Scored ${f2(r.points)} of a possible ${f2(r.optimal)}, ${when(r)}` })],
    ["losses_optimal_lineup_would_have_won", "Lost with a winning lineup on the bench", (r) => ({ value: f2(r.optimal), holder: r.manager, detail: `Lost ${f2(r.points)} to ${f2(r.opp_points)} vs ${esc(r.opponent)}, ${when(r)}` })],
  ]],
  ["Season", "season", [
    ["most_points_for", "Most points in a season", seasonRec((r) => f2(r.points_for))],
    ["fewest_points_for", "Fewest points in a season", seasonRec((r) => f2(r.points_for))],
    ["most_points_against", "Most points against", seasonRec((r) => f2(r.points_against))],
    ["best_record", "Best record", seasonRec((r) => r.record)],
    ["worst_record", "Worst record", seasonRec((r) => r.record)],
    ["luckiest", "Luckiest season", seasonRec((r) => signed(r.luck) + " wins")],
    ["unluckiest", "Unluckiest season", seasonRec((r) => signed(r.luck) + " wins")],
    ["best_lineup_efficiency", "Best lineup setter", seasonRec((r) => pct(r.lineup_efficiency))],
    ["worst_lineup_efficiency", "Worst lineup setter", seasonRec((r) => pct(r.lineup_efficiency))],
    ["most_weekly_high_scores", "Most weekly high scores", seasonRec((r) => r.weekly_high_scores)],
  ]],
  ["Players", "players", [
    ["highest_starter_score", "Best player game", playerRec(false)],
    ["highest_benched_score", "Best game left on the bench", playerRec(true)],
  ]],
  ["Streaks", "streaks", [
    ["longest_win_streak", "Longest win streak", streakRec],
    ["longest_loss_streak", "Longest losing streak", streakRec],
  ]],
  ["Waivers", "transactions", [
    ["biggest_faab_bids", "Biggest FAAB bid", (r) => ({ value: "$" + r.bid, holder: r.manager, detail: `${esc(r.player)}, ${r.season} week ${r.week}` })],
    ["most_faab_spent_season", "Most FAAB spent in a season", (r) => ({ value: "$" + r.spent, holder: r.manager, detail: r.season })],
    ["most_pickups_season", "Most pickups in a season", (r) => ({ value: r.pickups, holder: r.manager, detail: r.season })],
  ]],
];
$("records-body").innerHTML = GROUPS.map(([title, src, recs]) => `<h3>${title}</h3><div class="rec-grid">${recs.map(([key, label, fmt]) => {
  const list = (((D[src] || {})[key]) || []).slice(0, 5).map(fmt);
  if (!list.length) return `<div class="rec"><h4>${label}</h4><p class="empty">No entries yet.</p></div>`;
  const [lead, ...rest] = list;
  return `<div class="rec"><h4>${label}</h4>
    <div class="lead-value">${lead.value}</div>
    <div class="lead-holder">${esc(lead.holder)}</div>
    <div class="lead-detail">${lead.detail}</div>
    ${rest.length ? `<ol>${rest.map((x, i) => `<li><span class="n">${i + 2}</span><span>${esc(x.holder)}</span><span>${x.value}</span><span class="d">${x.detail}</span></li>`).join("")}</ol>` : ""}
  </div>`;
}).join("")}</div>`).join("");

/* ---------- managers ---------- */
table($("managers-table"), [
  ["Manager", (m) => [esc(m.manager), m.manager], "name"],
  ["Seasons", (m) => [m.seasons, m.seasons]],
  ["Record", (m) => [m.record, m.win_pct]],
  ["Win %", (m) => [pct(m.win_pct), m.win_pct]],
  ["PF", (m) => [f2(m.points_for), m.points_for]],
  ["PPG", (m) => [f2(m.ppg), m.ppg]],
  ["All-play %", (m) => [pct(m.all_play_pct), m.all_play_pct]],
  ["Playoffs", (m) => [m.playoff_appearances, m.playoff_appearances]],
  ["Playoff record", (m) => [m.playoff_record, recWins(m.playoff_record)]],
  ["Titles", (m) => [m.championships, m.championships]],
  ["Runner-up", (m) => [m.runner_ups, m.runner_ups]],
  ["Turkeys", (m) => [m.turkeys ?? 0, m.turkeys ?? 0]],
  ["High scores", (m) => [m.weekly_high_scores, m.weekly_high_scores]],
  ["Trades", (m) => [m.trades, m.trades]],
], D.managers);

const names = D.managers.map((m) => m.manager).sort((a, b) => a.localeCompare(b));
$("mgr-pick").innerHTML = names.map((n) => `<option>${esc(n)}</option>`).join("");
function showManager(name) {
  const t = [];
  D.history.forEach((h) => {
    if (h.champion === name) t.push(`champion in ${h.season}`);
    if (h.runner_up === name) t.push(`runner-up in ${h.season}`);
    if (h.third === name) t.push(`3rd in ${h.season}`);
    if (h.turkey === name) t.push(`wore the turkey after ${h.season}`);
  });
  $("mgr-trophies").textContent = t.length ? name + ": " + t.join(", ") + "." : `${name} has no finishes on the board yet.`;
  const rows = Object.entries(D.head_to_head[name] || {}).map(([opp, v]) => ({ opp, ...v }));
  table($("mgr-h2h"), [
    ["Opponent", (r) => [esc(r.opp), r.opp], "name"],
    ["Record", (r) => [`${r.w}-${r.l}${r.t ? "-" + r.t : ""}`, r.w - r.l]],
    ["PF", (r) => [f2(r.pf), r.pf]],
    ["PA", (r) => [f2(r.pa), r.pa]],
    ["Margin", (r) => { const d = r.pf - r.pa; return [`<span class="${d > 0 ? "pos" : d < 0 ? "neg" : ""}">${signed(d)}</span>`, d]; }],
  ], rows.sort((a, b) => a.opp.localeCompare(b.opp)));
}
$("mgr-pick").addEventListener("change", (e) => showManager(e.target.value));
if (names.length) showManager(names[0]);

/* ---------- head-to-head matrix ---------- */
$("h2h-table").innerHTML = `<thead><tr><th></th>${names.map((n) => `<th>${esc(n)}</th>`).join("")}</tr></thead><tbody>${
  names.map((a) => `<tr><td class="name">${esc(a)}</td>${names.map((b) => {
    if (a === b) return `<td class="self">&middot;</td>`;
    const v = (D.head_to_head[a] || {})[b];
    if (!v) return "<td></td>";
    const cls = v.w > v.l ? "w" : v.l > v.w ? "l" : "";
    return `<td class="${cls}">${v.w}-${v.l}${v.t ? "-" + v.t : ""}</td>`;
  }).join("")}</tr>`).join("")}</tbody>`;

/* ---------- seasons ---------- */
$("seasons-body").innerHTML = D.history.slice().reverse().map((h) => {
  const items = h.champion
    ? [["Champion", h.champion, "gold"], ["Wore the turkey", h.turkey, "bird"], ["Runner-up", h.runner_up], ["3rd place", h.third],
       ["Best record", h.best_record], ["Most points", h.most_points_for]]
    : [["Status", "In progress"], ["Best record so far", h.best_record], ["Most points so far", h.most_points_for]];
  return `<div class="season"><div class="yr">${h.season}</div><dl>${items.filter(([, v]) => v)
    .map(([k, v, c]) => `<div><dt>${k}</dt><dd class="${c || ""}">${esc(v)}</dd></div>`).join("")}</dl></div>`;
}).join("");

$("footer").textContent = `Updated through ${D.generated_through.season} week ${D.generated_through.week}. Data from Sleeper, refreshed every Tuesday.`;
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
