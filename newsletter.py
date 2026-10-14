#!/usr/bin/env python3
"""Draft the weekly newsletter for the latest finished week.

Writes newsletters/<season>-week-<NN>.md with status: draft. An existing file is
never overwritten, so your edits are safe.

Usage:
  python newsletter.py                  draft the latest finished week (skips if it exists)
  python newsletter.py --week 5         draft a specific week
  python newsletter.py --week 5 --force redo a draft (the old file is kept as .bak)

The stats are computed here. Claude only writes the prose (tagline, recap,
matchup preview, parting shots) from those stats. Without an ANTHROPIC_API_KEY
the draft still builds, with spots for you to write those parts yourself.
"""
import json
import os
import re
import sqlite3
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

CONFIG = {
    "model": "claude-sonnet-5-5",
    "voice": ("Funny and a little trash-talky, like a commissioner roasting his friends in the group chat. "
              "Playful, never mean-spirited, nothing crude. Short punchy sentences."),
}

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "league.db"
RECORDS_PATH = ROOT / "data" / "records.json"
RAW = ROOT / "data" / "raw"
OUT_DIR = ROOT / "newsletters"
PLAYED = ("regular", "playoff", "toilet_bowl")
NON_STARTER_SLOTS = {"BN", "IR", "TAXI"}
SLOT_ELIGIBILITY = {"FLEX": {"RB", "WR", "TE"}, "WRRB_FLEX": {"RB", "WR"}, "REC_FLEX": {"WR", "TE"},
                    "SUPER_FLEX": {"QB", "RB", "WR", "TE"}}

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row
rows = lambda q, *a: [dict(r) for r in con.execute(q, a)]
R = json.loads(RECORDS_PATH.read_text())
names = {r["user_id"]: r["name"] for r in rows("SELECT * FROM managers")}
nm = lambda u: names.get(u, u)
players = {r["player_id"]: r for r in rows("SELECT * FROM players")}
f2 = lambda x: f"{x:.2f}"

CUR = R["seasons"][0]
season = CUR["season"]
S = rows("SELECT * FROM seasons WHERE season = ?", season)[0]
final_weeks = sorted({g["week"] for g in rows("SELECT week FROM games WHERE season = ? AND is_final = 1 "
                                                 "AND game_type IN (?,?,?)", season, *PLAYED)})
args = sys.argv[1:]
week = int(args[args.index("--week") + 1]) if "--week" in args else (final_weeks[-1] if final_weeks else None)
if not week or week not in final_weeks:
    sys.exit("No finished week to write about yet.")
out_path = OUT_DIR / f"{season}-week-{week:02d}.md"
if out_path.exists() and "--force" not in args:
    print(f"{out_path.relative_to(ROOT)} already exists, leaving it alone.")
    sys.exit(0)

# ---------------------------------------------------------------- this week's facts

games = rows("SELECT * FROM games WHERE season = ? AND week = ? AND is_final = 1 AND opp_user_id IS NOT NULL "
             "AND game_type IN (?,?,?)", season, week, *PLAYED)
pw = rows("SELECT * FROM player_weeks WHERE season = ? AND week = ?", season, week)
slots = [p for p in json.loads(S["roster_positions"] or "[]") if p not in NON_STARTER_SLOTS]


def optimal(roster_id):
    pool = sorted([(r["points"] or 0, (players.get(r["player_id"]) or {}).get("position"))
                   for r in pw if r["roster_id"] == roster_id], reverse=True)
    used, total = set(), 0.0
    for slot in sorted(slots, key=lambda s: len(SLOT_ELIGIBILITY.get(s, {s}))):
        for i, (p, pos) in enumerate(pool):
            if i not in used and pos in SLOT_ELIGIBILITY.get(slot, {slot}):
                used.add(i)
                total += p
                break
    return total


def pinfo(pid):
    p = players.get(pid) or {}
    return p.get("name") or pid, p.get("position") or ""


pairs = [g for g in games if g["roster_id"] < g["opp_roster_id"]]
results = []
for g in pairs:
    a_won = g["points"] >= g["opp_points"]
    results.append({"winner": nm(g["user_id"] if a_won else g["opp_user_id"]),
                    "winner_points": max(g["points"], g["opp_points"]),
                    "loser": nm(g["opp_user_id"] if a_won else g["user_id"]),
                    "loser_points": min(g["points"], g["opp_points"]),
                    "margin": abs(g["points"] - g["opp_points"]), "type": g["game_type"]})
results.sort(key=lambda r: -r["winner_points"])

top = max(games, key=lambda g: g["points"])
bottom = min(games, key=lambda g: g["points"])
blowout = max(results, key=lambda r: r["margin"])
close = min(results, key=lambda r: r["margin"])

# upset: the biggest power-ranking gap overturned, using the ranks going into the week
rank_before = {}
if week in CUR["weeks"] and CUR["weeks"].index(week) > 0:
    i = CUR["weeks"].index(week) - 1
    rank_before = {p["manager"]: p["ranks"][i] for p in R.get("power", []) if len(p["ranks"]) > i}
upset = None
for r in results:
    a, b = rank_before.get(r["winner"]), rank_before.get(r["loser"])
    if a and b and a > b and (not upset or a - b > upset["gap"]):
        upset = {**r, "winner_rank": a, "loser_rank": b, "gap": a - b}

starters = [r for r in pw if r["is_starter"] and pinfo(r["player_id"])[1] in ("QB", "RB", "WR", "TE")]
potw = max(starters, key=lambda r: r["points"] or 0) if starters else None
dud = min(starters, key=lambda r: r["points"] or 0) if starters else None
bench = []
for g in games:
    left = max(optimal(g["roster_id"]) - g["points"], 0)
    best = max((r for r in pw if r["roster_id"] == g["roster_id"] and not r["is_starter"]),
               key=lambda r: r["points"] or 0, default=None)
    bench.append({"manager": nm(g["user_id"]), "left": left, "best": best, "lost": g["result"] == "L",
                  "would_have_won": g["result"] == "L" and g["points"] + left > g["opp_points"]})
blunder = max(bench, key=lambda b: (b["would_have_won"], b["left"]))

high = next((h for h in CUR["weekly_high_scores"] if h["week"] == week), None)

# record watch: anything from this week that landed on an all-time list
WATCH = [("highest_score", "highest score", "points", "manager"), ("lowest_score", "lowest score", "points", "manager"),
         ("biggest_blowout", "biggest blowout", "margin", "winner"), ("closest_game", "closest game", "margin", "winner"),
         ("highest_combined", "highest-scoring matchup", "combined", "winner"),
         ("most_points_left_on_bench", "most points left on the bench", "left_on_bench", "manager")]
record_watch = []
for key, label, val, who in WATCH:
    for i, r in enumerate(R["single_game"].get(key, [])):
        if r["season"] == season and r["week"] == week:
            record_watch.append(f"{r[who]}'s {f2(r[val])} is the {['', '', '2nd', '3rd', '4th', '5th'][i + 1] + ' ' if i else ''}"
                                f"{label} in league history.")
for r in R["players"].get("highest_starter_score", []):
    if r["season"] == season and r["week"] == week:
        record_watch.append(f"{r['player']}'s {f2(r['points'])} for {r['manager']} is one of the 5 best player games in league history.")
        break
streaks = R.get("streaks", {}).get("current", {})
active = {r["manager"] for r in CUR["standings"]}   # managers in the league this season
hot = sorted([(int(v[1:]), m) for m, v in streaks.items() if m in active and v.startswith("W") and int(v[1:]) >= 3], reverse=True)
cold = sorted([(int(v[1:]), m) for m, v in streaks.items() if m in active and v.startswith("L") and int(v[1:]) >= 3], reverse=True)

# transactions
trades = []
for t in rows("SELECT * FROM transactions WHERE season = ? AND week = ? AND type = 'trade' AND status = 'complete'", season, week):
    got = defaultdict(list)
    for m in rows("SELECT * FROM transaction_moves WHERE transaction_id = ? AND action = 'add'", t["transaction_id"]):
        got[nm(m["user_id"])].append(pinfo(m["player_id"])[0])
    for f in rows("SELECT * FROM transaction_faab WHERE transaction_id = ?", t["transaction_id"]):
        got[nm(f["to_user_id"])].append(f"${f['amount']} FAAB")
    trades.append(dict(got))
bid = rows("SELECT t.waiver_bid, m.user_id, m.player_id FROM transactions t JOIN transaction_moves m USING (transaction_id) "
           "WHERE t.season = ? AND t.week = ? AND t.type = 'waiver' AND t.status = 'complete' AND m.action = 'add' "
           "ORDER BY t.waiver_bid DESC LIMIT 1", season, week)
bid = bid[0] if bid and bid[0]["waiver_bid"] else None

# ---------------------------------------------------------------- next week

nxt = week + 1
owner = {r["roster_id"]: r["user_id"] for r in rows("SELECT * FROM teams WHERE season = ?", season)}
slate = []
if nxt < S["playoff_week_start"]:
    p = RAW / season / "matchups" / f"{nxt:02d}.json"
    groups = defaultdict(list)
    for e in (json.loads(p.read_text()) if p.exists() else []) or []:
        if e.get("matchup_id") is not None:
            groups[e["matchup_id"]].append(nm(owner.get(e["roster_id"])))
    slate = [(g[0], g[1], None) for g in groups.values() if len(g) == 2]
else:
    slate = [(b["t1"], b["t2"], b["name"]) for b in CUR["brackets"] if b["week"] == nxt and b["t1"] and b["t2"]]

power_now = {p["manager"]: p for p in R.get("power", [])}
standing = {r["manager"]: r for r in CUR["standings"]}
odds = R.get("playoff_odds", {})


def series(a, b):
    v = R["head_to_head"].get(a, {}).get(b)
    if not v or not (v["w"] + v["l"] + v["t"]):
        return "First meeting"
    if v["w"] == v["l"]:
        return f"Series tied {v['w']}-{v['l']}" + (f"-{v['t']}" if v["t"] else "")
    lead, w, l = (a, v["w"], v["l"]) if v["w"] > v["l"] else (b, v["l"], v["w"])
    return f"{lead} leads {w}-{l}" + (f"-{v['t']}" if v["t"] else "")


def rk(m):
    return power_now.get(m, {}).get("rank", 99)


motw = min(slate, key=lambda s: rk(s[0]) + rk(s[1])) if slate else None
turkey_watch = sorted(CUR["standings"], key=lambda r: r["seed"])[-3:] if not CUR["regular_complete"] else []

# ---------------------------------------------------------------- prose from Claude

facts = {
    "league": S["name"], "season": season, "week": week,
    "results": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()} for r in results],
    "top_score": {"manager": nm(top["user_id"]), "points": round(top["points"], 2)},
    "bottom_score": {"manager": nm(bottom["user_id"]), "points": round(bottom["points"], 2)},
    "upset": upset and {"winner": upset["winner"], "winner_rank_before": upset["winner_rank"],
                        "loser": upset["loser"], "loser_rank_before": upset["loser_rank"]},
    "player_of_the_week": potw and {"player": pinfo(potw["player_id"])[0], "points": potw["points"], "manager": nm(potw["user_id"])},
    "biggest_dud": dud and {"player": pinfo(dud["player_id"])[0], "points": dud["points"], "manager": nm(dud["user_id"])},
    "bench_blunder": {"manager": blunder["manager"], "points_left_on_bench": round(blunder["left"], 2),
                      "would_have_won_with_best_lineup": blunder["would_have_won"]},
    "record_watch": record_watch,
    "win_streaks": [f"{m} has won {n} straight" for n, m in hot],
    "losing_streaks": [f"{m} has lost {n} straight" for n, m in cold],
    "trades": trades,
    "power_rankings": [{"rank": p["rank"], "manager": p["manager"], "move": p["move"], "record": p["record"]} for p in R.get("power", [])],
    "matchup_of_the_week": motw and {"a": motw[0], "b": motw[1], "series": series(motw[0], motw[1]),
                                     "a_rank": rk(motw[0]), "b_rank": rk(motw[1]),
                                     "a_record": standing.get(motw[0], {}).get("record"), "b_record": standing.get(motw[1], {}).get("record")},
    "turkey_watch": [r["manager"] for r in turkey_watch],
}


def claude_prose():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("No ANTHROPIC_API_KEY set, leaving the write-ups for you.")
        return {}
    system = (f"You write the weekly newsletter for a fantasy football league called {S['name']}. "
              "Use only the facts you are given. Never invent scores, stats, injuries, quotes or events. "
              f"Voice: {CONFIG['voice']} Never use em dashes or en dashes. "
              "Return only a JSON object, no other text, with these string keys: "
              "tagline (one punchy sentence about the week), "
              "recap (two or three short paragraphs separated by a blank line, covering the biggest storylines), "
              "motw (one short paragraph previewing the matchup of the week, empty string if there is none), "
              "parting_shots (one or two short closing lines).")
    body = {"model": CONFIG["model"], "max_tokens": 1500, "system": system,
            "messages": [{"role": "user", "content": json.dumps(facts, default=str)}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        out = json.loads(text)
        return {k: re.sub(r"\s*[\u2014\u2013]\s*", ", ", str(v)).strip() for k, v in out.items()}
    except Exception as e:  # the draft still gets written; you fill in the prose
        print(f"Claude did not return a write-up ({e}). Leaving the write-ups for you.")
        return {}


prose = claude_prose()
blank = lambda what: f"_Write {what} here._"

# ---------------------------------------------------------------- the draft

L = [f"---", f"title: Week {week}", f"season: {season}", f"week: {week}", "status: draft", "---",
     "<!-- This is a draft. Edit anything you like. To post it on the site, change status: draft to "
     "status: published above and commit. -->", ""]
L += [f"# {S['name']} Weekly, Week {week}", "", (f"*{prose['tagline']}*" if prose.get("tagline") else blank("a one-line tagline")), ""]
L += ["## The recap", "", prose.get("recap") or blank("the recap"), ""]

L += ["## Headlines", ""]
L.append(f"- **Top score:** {nm(top['user_id'])}, {f2(top['points'])}")
L.append(f"- **Bottom score:** 💩 {nm(bottom['user_id'])}, {f2(bottom['points'])}")
L.append(f"- **Biggest blowout:** {blowout['winner']} over {blowout['loser']} by {f2(blowout['margin'])}")
L.append(f"- **Nail-biter:** {close['winner']} over {close['loser']} by {f2(close['margin'])}")
if upset:
    L.append(f"- **Upset of the week:** #{upset['winner_rank']} {upset['winner']} beat #{upset['loser_rank']} {upset['loser']}")
if potw:
    n, pos = pinfo(potw["player_id"])
    L.append(f"- **Player of the week:** {n} ({pos}), {f2(potw['points'])} for {nm(potw['user_id'])}")
if dud:
    n, pos = pinfo(dud["player_id"])
    L.append(f"- **Biggest dud:** {n} ({pos}), {f2(dud['points'])} for {nm(dud['user_id'])}")
if blunder["left"] > 0:
    extra = " and would have won with the best lineup" if blunder["would_have_won"] else ""
    best = f" ({pinfo(blunder['best']['player_id'])[0]} scored {f2(blunder['best']['points'])} on the bench)" if blunder["best"] else ""
    L.append(f"- **Bench blunder:** {blunder['manager']} left {f2(blunder['left'])} points on the bench{extra}{best}")
if high and CUR.get("weekly_prize"):
    L.append(f"- **Weekly prize:** {' and '.join(high['managers'])} take{'s' if len(high['managers']) == 1 else ''} "
             f"the ${CUR['weekly_prize']}" + (" (split)" if len(high["managers"]) > 1 else ""))
L.append("")

L += ["## Scoreboard", "", "| Winner | Score | Loser | Score |", "|---|---:|---|---:|"]
L += [f"| {r['winner']} | {f2(r['winner_points'])} | {r['loser']} | {f2(r['loser_points'])} |" for r in results]
L.append("")

if R.get("power") and week == CUR["weeks"][-1]:
    L += ["## Power rankings", "", "| # | Move | Manager | Record | Power |", "|---:|:---:|---|---|---:|"]
    for p in R["power"]:
        mv = f"▲{p['move']}" if p["move"] > 0 else f"▼{-p['move']}" if p["move"] < 0 else "-"
        L.append(f"| {p['rank']} | {mv} | {p['manager']} | {p['record']} | {p['power']:.1f} |")
    riser = max(R["power"], key=lambda p: p["move"])
    faller = min(R["power"], key=lambda p: p["move"])
    if riser["move"] > 0:
        L += ["", f"**Riser:** {riser['manager']}, up {riser['move']} to #{riser['rank']}. "
                  + (f"**Faller:** {faller['manager']}, down {-faller['move']} to #{faller['rank']}." if faller["move"] < 0 else "")]
    L.append("")

notes = list(record_watch)
if hot:
    notes.append("**Win streaks:** " + ", ".join(f"{m} {n}" for n, m in hot))
if cold:
    notes.append("**Losing streaks:** " + ", ".join(f"{m} {n}" for n, m in cold))
if notes:
    L += ["## Record watch", ""] + [f"- {x}" for x in notes] + [""]

if trades or bid:
    L += ["## Around the league", ""]
    for t in trades:
        L.append("- **Trade:** " + "; ".join(f"{m} gets {', '.join(p)}" for m, p in t.items()))
    if bid:
        L.append(f"- **Biggest FAAB bid:** {nm(bid['user_id'])} paid ${bid['waiver_bid']} for {pinfo(bid['player_id'])[0]}")
    L.append("")

if slate:
    L += [f"## Week {nxt} preview", ""]
    if motw:
        a, b, rnd = motw
        L += [f"### Matchup of the week: {a} vs {b}" + (f" ({rnd})" if rnd else ""), "",
              f"| | {a} | {b} |", "|---|---:|---:|"]
        sa, sb = standing.get(a, {}), standing.get(b, {})
        pa, pb = power_now.get(a, {}), power_now.get(b, {})
        L.append(f"| Record | {sa.get('record', '')} | {sb.get('record', '')} |")
        L.append(f"| Power rank | {pa.get('rank', '')} | {pb.get('rank', '')} |")
        L.append(f"| Points per game | {f2(sa['ppg']) if sa else ''} | {f2(sb['ppg']) if sb else ''} |")
        L.append(f"| Last 3 | {f2(pa['last3']) if pa else ''} | {f2(pb['last3']) if pb else ''} |")
        if odds:
            L.append(f"| Playoff odds | {round(odds.get(a, {}).get('make', 0) * 100)}% | {round(odds.get(b, {}).get('make', 0) * 100)}% |")
        L += ["", f"**Series:** {series(a, b)}", "", prose.get("motw") or blank("the matchup preview"), ""]
    L += ["### The slate", "", "| Matchup | Records | Series |", "|---|---|---|"]
    for a, b, rnd in slate:
        rec = f"{standing.get(a, {}).get('record', '')} vs {standing.get(b, {}).get('record', '')}"
        L.append(f"| {a} vs {b}{' (' + rnd + ')' if rnd else ''} | {rec} | {series(a, b)} |")
    L.append("")

if turkey_watch:
    L += ["## Turkey watch", "", "If the season ended today, these three would be closest to the costume:", ""]
    for r in turkey_watch:
        o = odds.get(r["manager"])
        L.append(f"- {r['manager']}, {r['record']}" + (f", {round(o['make'] * 100)}% to make the playoffs" if o else ""))
    L.append("")

L += ["## Parting shots", "", prose.get("parting_shots") or blank("your parting shots"), ""]

OUT_DIR.mkdir(exist_ok=True)
if out_path.exists():
    out_path.rename(out_path.with_suffix(".md.bak"))
out_path.write_text("\n".join(L), encoding="utf-8")
print(f"Wrote {out_path.relative_to(ROOT)} (draft)")
