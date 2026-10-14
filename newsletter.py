#!/usr/bin/env python3
"""The Turkey Bowl Weekly: a draft you can edit, rendered to an image for the group chat.

Each finished week gets these files in newsletters/:
  <season>-week-<NN>.md     the text boxes and the two featured games. Edit this one.
  <season>-week-<NN>.json   the week's stats, frozen when the draft was made
  <season>-week-<NN>.jpg    the newsletter image to send

Usage:
  python newsletter.py                  draft the latest finished week if it has no draft, then render
  python newsletter.py --week 5         draft a specific week (skips if it exists)
  python newsletter.py --week 5 --force redo that draft (the old .md is kept as .md.bak)
  python newsletter.py --render-only    only re-render images whose text changed

Stats are computed here. Claude only writes the text boxes, from those stats.
Without an ANTHROPIC_API_KEY the draft still builds and the empty boxes are left out.
"""
import base64
import hashlib
import json
import os
import re
import sqlite3
import sys
import urllib.request
from collections import defaultdict
from html import escape
from pathlib import Path

CONFIG = {
    "model": "claude-sonnet-5-5",
    "voice": ("Casual and funny, like a commissioner roasting his friends in the group chat. "
              "Playful, never mean-spirited, nothing crude. Short and punchy. An occasional emoji is fine."),
}
TEMPLATE_VERSION = "1"

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "league.db"
RECORDS_PATH = ROOT / "data" / "records.json"
RAW = ROOT / "data" / "raw"
OUT = ROOT / "newsletters"
TURKEY_DIR = OUT / "turkey"
PLAYED = ("regular", "playoff", "toilet_bowl")
NON_STARTER_SLOTS = {"BN", "IR", "TAXI"}
SLOT_ELIGIBILITY = {"FLEX": {"RB", "WR", "TE"}, "WRRB_FLEX": {"RB", "WR"}, "REC_FLEX": {"WR", "TE"},
                    "SUPER_FLEX": {"QB", "RB", "WR", "TE"}}
INJURY_CODE = {"Questionable": "Q", "Doubtful": "D", "Out": "O", "IR": "IR", "PUP": "PUP", "Sus": "SUS"}
SECTIONS = [("recap", "The recap"), ("what_happened", "What happened"), ("injuries", "Injury report"),
            ("trade_talk", "Trade talks"), ("breakdown", "The breakdown"), ("basement", "The latest from the basement")]


# ================================================================= drafting

def draft(week_arg, force):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = lambda q, *a: [dict(r) for r in con.execute(q, a)]
    R = json.loads(RECORDS_PATH.read_text())
    names = {r["user_id"]: r["name"] for r in rows("SELECT * FROM managers")}
    nm = lambda u: names.get(u, u)
    players = {r["player_id"]: r for r in rows("SELECT * FROM players")}
    pname = lambda pid: (players.get(pid) or {}).get("name") or pid
    ppos = lambda pid: (players.get(pid) or {}).get("position") or ""

    CUR = R["seasons"][0]
    season = CUR["season"]
    S = rows("SELECT * FROM seasons WHERE season = ?", season)[0]
    done = sorted({g["week"] for g in rows("SELECT week FROM games WHERE season = ? AND is_final = 1 "
                                           "AND game_type IN (?,?,?)", season, *PLAYED)})
    week = week_arg or (done[-1] if done else None)
    if not week or week not in done:
        print("No finished week to write about yet.")
        return
    md_path = OUT / f"{season}-week-{week:02d}.md"
    if md_path.exists() and not force:
        print(f"{md_path.name} already exists, leaving it alone.")
        return

    games = rows("SELECT * FROM games WHERE season = ? AND week = ? AND is_final = 1 AND opp_user_id IS NOT NULL "
                 "AND game_type IN (?,?,?)", season, week, *PLAYED)
    pw = rows("SELECT * FROM player_weeks WHERE season = ? AND week = ?", season, week)
    slots = [p for p in json.loads(S["roster_positions"] or "[]") if p not in NON_STARTER_SLOTS]

    def optimal(rid):
        pool = sorted([(r["points"] or 0, ppos(r["player_id"])) for r in pw if r["roster_id"] == rid], reverse=True)
        used, total = set(), 0.0
        for slot in sorted(slots, key=lambda s: len(SLOT_ELIGIBILITY.get(s, {s}))):
            for i, (p, pos) in enumerate(pool):
                if i not in used and pos in SLOT_ELIGIBILITY.get(slot, {slot}):
                    used.add(i)
                    total += p
                    break
        return total

    standing = {r["manager"]: r for r in CUR["standings"]}
    power = {p["manager"]: p for p in R.get("power", [])}
    odds = R.get("playoff_odds", {})
    wi = CUR["weeks"].index(week) if week in CUR["weeks"] else None
    rank_before = {p["manager"]: p["ranks"][wi - 1] for p in R.get("power", []) if wi and len(p["ranks"]) >= wi}

    # this week, one entry per team
    team_week = {}
    for g in games:
        best = max((r for r in pw if r["roster_id"] == g["roster_id"] and not r["is_starter"]),
                   key=lambda r: r["points"] or 0, default=None)
        team_week[nm(g["user_id"])] = {
            "points": g["points"], "result": g["result"], "opponent": nm(g["opp_user_id"]), "opp_points": g["opp_points"],
            "bench_left": max(optimal(g["roster_id"]) - g["points"], 0),
            "best_bench": {"player": pname(best["player_id"]), "points": best["points"]} if best else None}
    results = []
    for g in games:
        if g["roster_id"] > g["opp_roster_id"]:
            continue
        aw = g["points"] >= g["opp_points"]
        results.append({"winner": nm(g["user_id"] if aw else g["opp_user_id"]), "loser": nm(g["opp_user_id"] if aw else g["user_id"]),
                        "winner_points": max(g["points"], g["opp_points"]), "loser_points": min(g["points"], g["opp_points"]),
                        "margin": abs(g["points"] - g["opp_points"]), "type": g["game_type"]})

    top = max(team_week.items(), key=lambda kv: kv[1]["points"])
    bottom = min(team_week.items(), key=lambda kv: kv[1]["points"])
    blowout = max(results, key=lambda r: r["margin"])
    close = min(results, key=lambda r: r["margin"])
    upset = None
    for r in results:
        a, b = rank_before.get(r["winner"]), rank_before.get(r["loser"])
        if a and b and a > b and (not upset or a - b > upset["gap"]):
            upset = {"winner": r["winner"], "loser": r["loser"], "winner_rank": a, "loser_rank": b, "gap": a - b}
    starters = [r for r in pw if r["is_starter"] and ppos(r["player_id"]) in ("QB", "RB", "WR", "TE")]
    potw = max(starters, key=lambda r: r["points"] or 0, default=None)
    dud = min(starters, key=lambda r: r["points"] or 0, default=None)
    blunder_m, blunder = max(team_week.items(), key=lambda kv: kv[1]["bench_left"])

    # injuries on current rosters
    owner = {r["roster_id"]: r["user_id"] for r in rows("SELECT * FROM teams WHERE season = ?", season)}
    injuries = defaultdict(list)
    rp = RAW / season / "rosters.json"
    for r in (json.loads(rp.read_text()) if rp.exists() else []):
        for pid in r.get("players") or []:
            st = (players.get(pid) or {}).get("injury_status")
            if st in INJURY_CODE:
                injuries[nm(r.get("owner_id"))].append([pname(pid), INJURY_CODE[st]])

    # trades
    trades = []
    for t in rows("SELECT * FROM transactions WHERE season = ? AND week = ? AND type = 'trade' AND status = 'complete'", season, week):
        got = defaultdict(list)
        for m in rows("SELECT * FROM transaction_moves WHERE transaction_id = ? AND action = 'add'", t["transaction_id"]):
            got[nm(m["user_id"])].append(pname(m["player_id"]))
        for f in rows("SELECT * FROM transaction_faab WHERE transaction_id = ?", t["transaction_id"]):
            got[nm(f["to_user_id"])].append(f"${f['amount']} FAAB")
        trades.append(dict(got))

    # next week
    nxt = week + 1
    if nxt < S["playoff_week_start"]:
        p = RAW / season / "matchups" / f"{nxt:02d}.json"
        groups = defaultdict(list)
        for e in (json.loads(p.read_text()) if p.exists() else []) or []:
            if e.get("matchup_id") is not None:
                groups[e["matchup_id"]].append(nm(owner.get(e["roster_id"])))
        slate = [[g[0], g[1], None] for g in groups.values() if len(g) == 2]
    else:
        slate = [[b["t1"], b["t2"], b["name"]] for b in CUR["brackets"] if b["week"] == nxt and b["t1"] and b["t2"]]

    pscore = lambda m: (power.get(m) or {}).get("power", 0)
    # the main event: the most evenly matched game on next week's slate
    main_event = min(slate, key=lambda s: (abs(pscore(s[0]) - pscore(s[1])), -(pscore(s[0]) + pscore(s[1])))) if slate else None

    # game rewind: last issue's main event, else the closest game
    rewind = None
    prev = OUT / f"{season}-week-{week - 1:02d}.md"
    if prev.exists():
        pair = split_pair(read_md(prev)[0].get("main_event", ""))
        if pair and any({r["winner"], r["loser"]} == set(pair) for r in results):
            rewind = f"{pair[0]} vs {pair[1]}"
    rewind = rewind or f"{close['winner']} vs {close['loser']}"

    # turkey: last place in the standings, or the decided turkey once the season is over
    turkey = CUR.get("turkey") or (max(CUR["standings"], key=lambda r: r["seed"])["manager"] if CUR["standings"] else None)

    current = [r["manager"] for r in CUR["standings"]]
    h2h = {f"{a}|{b}": [v["w"], v["l"], v["t"]] for a in current for b in current
           if (v := R["head_to_head"].get(a, {}).get(b))}
    teams = {}
    for m in current:
        s_, p_ = standing.get(m, {}), power.get(m, {})
        teams[m] = {"record": s_.get("record"), "seed": s_.get("seed"), "ppg": s_.get("ppg"),
                    "power_rank": p_.get("rank"), "move": p_.get("move", 0), "last3": p_.get("last3"),
                    "odds": (odds.get(m) or {}).get("make"), "week": team_week.get(m)}
    latest = wi is not None and wi == len(CUR["weeks"]) - 1

    facts = {
        "league": S["name"], "season": season, "week": week, "next_week": nxt,
        "playoff_teams": S["playoff_teams"] or 6, "regular_complete": CUR["regular_complete"],
        "top": {"manager": top[0], "points": top[1]["points"]},
        "bottom": {"manager": bottom[0], "points": bottom[1]["points"]},
        "blowout": blowout, "close": close, "upset": upset,
        "potw": potw and {"player": pname(potw["player_id"]), "points": potw["points"], "manager": nm(potw["user_id"])},
        "dud": dud and {"player": pname(dud["player_id"]), "points": dud["points"], "manager": nm(dud["user_id"])},
        "blunder": {"manager": blunder_m, "left": blunder["bench_left"], "best": blunder["best_bench"]},
        "results": results, "teams": teams, "h2h": h2h,
        "power": [{k: p[k] for k in ("rank", "move", "manager", "record", "power", "win_pct", "all_play_pct", "ppg", "last3", "scores")}
                  for p in R.get("power", [])] if latest else [],
        "injuries": dict(injuries), "trades": trades, "slate": slate, "turkey": turkey,
    }
    OUT.mkdir(exist_ok=True)
    md_path.with_suffix(".json").write_text(json.dumps(facts, indent=1, default=str), encoding="utf-8")

    text = claude_text(facts, main_event, rewind)
    lines = ["---", f"season: {season}", f"week: {week}",
             f"main_event: {main_event[0]} vs {main_event[1]}" if main_event else "main_event:",
             f"rewind: {rewind}", "---",
             "<!-- Edit the text under each heading, then commit. The image rebuilds in a couple of minutes as "
             f"{md_path.with_suffix('.jpg').name}. Leave a section empty to drop its box. main_event (next week) and "
             "rewind (this week) pick the two featured games; use the exact names, like Emily vs Mitchel. -->", ""]
    for key, title in SECTIONS:
        if key == "trade_talk" and not trades:
            continue
        lines += [f"## {title}", "", text.get(key, ""), ""]
    if md_path.exists():
        md_path.rename(md_path.with_suffix(".md.bak"))
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {md_path.name} and its stats")


def claude_text(facts, main_event, rewind):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("No ANTHROPIC_API_KEY set, leaving the text boxes for you.")
        return {}
    brief = {k: facts[k] for k in ("league", "week", "top", "bottom", "blowout", "close", "upset", "potw", "dud",
                                   "blunder", "results", "injuries", "trades", "turkey")}
    brief["standings"] = {m: {k: t[k] for k in ("record", "power_rank", "move", "ppg")} for m, t in facts["teams"].items()}
    brief["game_rewind"] = rewind
    brief["main_event_next_week"] = main_event and f"{main_event[0]} vs {main_event[1]}"
    system = (f"You write the text boxes for {facts['league']}'s weekly fantasy football newsletter. "
              "Use only the facts given. Never invent scores, stats, injuries, quotes or events. "
              f"Voice: {CONFIG['voice']} Never use em dashes or en dashes. "
              "Return only a JSON object, no other text, with these string keys, each 1 to 3 sentences: "
              "recap (the week's biggest storylines), what_happened (the game rewind result), "
              "injuries (a quip about the injury report), breakdown (preview of next week's main event, empty if none), "
              "basement (about the team in last place, the one closest to wearing the turkey costume)"
              + (", trade_talk (about this week's trades)" if facts["trades"] else "") + ".")
    body = {"model": CONFIG["model"], "max_tokens": 1200, "system": system,
            "messages": [{"role": "user", "content": json.dumps(brief, default=str)}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
        out = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        out = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", out))
        return {k: re.sub(r"\s*[\u2014\u2013]\s*", ", ", str(v)).strip() for k, v in out.items()}
    except Exception as e:
        print(f"Claude did not return the text ({e}). Leaving the text boxes for you.")
        return {}


# ================================================================= reading the draft

def read_md(path):
    text = path.read_text(encoding="utf-8")
    meta, body = {}, text
    if text.startswith("---"):
        head, _, body = text[3:].partition("\n---")
        for line in head.strip().splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    sections, cur = {}, None
    titles = {t.lower(): k for k, t in SECTIONS}
    for line in body.splitlines():
        if line.startswith("## "):
            cur = titles.get(line[3:].strip().lower())
            if cur:
                sections[cur] = []
        elif cur:
            sections[cur].append(line)
    return meta, {k: "\n".join(v).strip() for k, v in sections.items()}


def split_pair(s):
    parts = [p.strip() for p in re.split(r"\s+vs\.?\s+", s or "", flags=re.I)]
    return parts if len(parts) == 2 and all(parts) else None


# ================================================================= rendering

CSS = """
*{box-sizing:border-box}
body{margin:0;width:780px;background:#fff;color:#1b2140;font:400 13px/1.45 Roboto,Arial,sans-serif}
.mast{background:#121a3a;color:#fff;text-align:center;padding:20px 0 18px}
.vol{color:#f9b52c;font:600 12px Oswald,sans-serif;letter-spacing:.06em}
.title{font:700 46px/1.1 Oswald,sans-serif;letter-spacing:.01em;margin:8px 0 10px;display:flex;align-items:center;justify-content:center;gap:16px}
.title .e{font-size:40px}
.sub{color:#f9b52c;font:600 13px Oswald,sans-serif;letter-spacing:.42em}
.stripe{height:7px;background:linear-gradient(90deg,#1fcfae 0 33.3%,#f9b52c 33.3% 66.6%,#f2577d 66.6%)}
.stripe.rev{background:linear-gradient(90deg,#f2577d 0 33.3%,#f9b52c 33.3% 66.6%,#1fcfae 66.6%)}
.band{background:#1b2350;color:#f9b52c;text-align:center;font:600 15px Oswald,sans-serif;letter-spacing:.02em;padding:8px;border-top:3px solid #121a3a;border-bottom:3px solid #121a3a}
.pad{padding:18px 22px}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.tile{padding:12px 12px 10px;min-height:112px;display:flex;flex-direction:column}
.tile .l{font:600 11px Oswald,sans-serif;letter-spacing:.02em}
.tile .v{font:700 34px/1.1 Oswald,sans-serif;margin:10px 0 auto}
.tile .n{font:500 12px Oswald,sans-serif;margin-top:8px}
.teal{background:#1fcfae;color:#0f1a33}.pink{background:#f2577d;color:#fff}.navy{background:#1b2350;color:#fff}.gold{background:#fbb22b;color:#1b2140}
.two{display:grid;grid-template-columns:1.12fr 1fr;gap:18px;margin-top:12px;align-items:start}
h4{font:600 14px Oswald,sans-serif;margin:0 0 6px;letter-spacing:.01em}
.also{width:100%;border-collapse:collapse;font-size:11px}
.also td{border:1px solid #d9dceb;padding:6px 7px;vertical-align:top}
.also td:first-child{font:600 11px Oswald,sans-serif;background:#f1f2f8;width:30%}
.box{padding:12px 16px;font-size:12.5px}
.recap{background:#eef0f8;border-left:5px solid #1fcfae}
.cream{background:#fdf5e3;color:#1b2140;border-left:5px solid #1fcfae}
.cream.g{border-left-color:#fbb22b}
.dark{background:#121a3a;color:#fff}
.sh{display:flex;align-items:center;gap:10px;font:700 22px Oswald,sans-serif;letter-spacing:.01em;margin:0 0 4px}
.rule{height:4px;margin-bottom:14px;background:linear-gradient(90deg,#1fcfae 0 70px,#f9b52c 70px 140px,#dfe2ef 140px)}
.dark .rule{background:linear-gradient(90deg,#1fcfae 0 70px,#f9b52c 70px 140px,#2b3463 140px)}
.vs{display:grid;grid-template-columns:1fr 88px 1fr;align-items:stretch}
.vs .side{padding:14px}
.vs .side.r{text-align:right}
.vs .nm{font:700 22px/1.1 Oswald,sans-serif;text-transform:uppercase}
.vs .nm.big2{font-size:32px;text-transform:none}
.vs .big{font:700 30px/1.1 Oswald,sans-serif;margin-top:8px}
.vs .mid{display:flex;align-items:center;justify-content:center;color:#f9b52c;font:700 22px Oswald,sans-serif}
.vs .mid.l{font-size:34px}
.vs .tag{font:600 11px Oswald,sans-serif;margin-top:8px;letter-spacing:.03em}
.cmp{width:100%;border-collapse:collapse;margin-top:2px}
.cmp td{padding:6px 14px;font:600 13px Oswald,sans-serif;width:40%}
.cmp tr:nth-child(odd){background:#1b2350}
.cmp td:nth-child(2){text-align:center;color:#f9b52c;font-size:10px;letter-spacing:.04em;width:20%}
.cmp td:last-child{text-align:right}
.cmp.lg td{font-size:17px}
.cmp.lg td:nth-child(2){font-size:10px}
.foot{text-align:center;color:#1fcfae;font:600 13px Oswald,sans-serif;margin:10px 0 12px}
table.pr{width:100%;border-collapse:collapse;font-size:10.5px}
.pr th{background:#1b2350;color:#fff;font:600 10px Oswald,sans-serif;text-align:left;padding:4px 5px;border:1px solid #fff}
.pr td{padding:4px 5px;border:1px solid #e3e6f1;height:30px}
.up{color:#1aa88f;font-weight:700}.down{color:#e8466c;font-weight:700}
.rf{display:flex;justify-content:space-between;font:600 11px Oswald,sans-serif;margin-top:8px}
.injury{background:#fde2e8;border-left:5px solid #f2577d;padding:12px 16px}
.injury .list{font:400 11.5px/1.7 "Roboto Condensed",Roboto,sans-serif}
.injury .k{font-size:9px;color:#8a90b0;margin:4px 0 6px}
.code{font-weight:700}.code.bad{color:#e8466c}
.ttab{border-collapse:collapse;width:100%;font-size:12px}
.ttab td{border:1px solid #d9dceb;padding:6px 10px}
.ttab td:first-child{color:#8a90b0;text-align:center;width:36%;font-size:10px}
.ttab tr:first-child td{background:#1b2350;color:#fff;font:700 16px Oswald,sans-serif;text-align:center}
.ttab tr:first-child td:last-child{color:#f9b52c;font-size:11px;text-align:left}
.ttab td:last-child{font:600 12px Oswald,sans-serif}
.tk{display:grid;grid-template-columns:1fr 200px;gap:20px;align-items:center}
.tk img{width:200px;height:200px;object-fit:cover;border-radius:6px}
.tk .emo{font-size:150px;line-height:1;text-align:center}
.wrapup{background:#121a3a;color:#fff;text-align:center;font:700 19px Oswald,sans-serif;padding:20px}
.trade{border-collapse:collapse;width:100%;font-size:12px;margin-bottom:10px}
.trade td{border:1px solid #d9dceb;padding:6px 9px}
.trade td:first-child{font:600 12px Oswald,sans-serif;width:28%;background:#f1f2f8}
"""


def f2(x):
    return "" if x is None else f"{x:.2f}"


def spark(vals):
    v = [x for x in (vals or []) if x is not None]
    if not v:
        return ""
    mx, mn, w, h = max(v), min(v) * 0.8, 5, 20
    hh = lambda x: max(2, (x - mn) / ((mx - mn) or 1) * h)
    return (f'<svg width="{len(v) * (w + 1)}" height="{h}">' + "".join(
        f'<rect x="{i * (w + 1)}" y="{h - hh(x):.1f}" width="{w}" height="{hh(x):.1f}" fill="#1aa88f"/>'
        for i, x in enumerate(v)) + "</svg>")


def tint(v, lo, hi):
    t = 0.5 if hi == lo else (v - lo) / (hi - lo)
    return f"rgba(31,207,174,{0.08 + 0.4 * (t - 0.5):.2f})" if t >= 0.5 else f"rgba(242,87,125,{0.08 + 0.4 * (0.5 - t):.2f})"


def turkey_img(name):
    for stem in (name, "default"):
        for ext in ("png", "jpg", "jpeg", "webp"):
            p = TURKEY_DIR / f"{stem}.{ext}"
            if p.exists():
                mime = "jpeg" if ext in ("jpg", "jpeg") else ext
                return f'<img src="data:image/{mime};base64,{base64.b64encode(p.read_bytes()).decode()}" alt="">'
    return '<div class="emo">🦃</div>'


def para(text):
    return "".join(f"<p style='margin:0 0 6px'>{escape(p.strip())}</p>" for p in re.split(r"\n\s*\n", text) if p.strip())


def series(F, a, b):
    w, l, t = F["h2h"].get(f"{a}|{b}", [0, 0, 0])
    if not (w + l + t):
        return "✖ First ever meeting"
    if w == l:
        return f"Series tied {w}-{l}" + (f"-{t}" if t else "")
    return (f"{a} leads the series {w}-{l}" if w > l else f"{b} leads the series {l}-{w}") + (f"-{t}" if t else "")


def render_html(F, meta, T):
    e = escape
    wk, nxt = F["week"], F["next_week"]
    H = ["<!doctype html><html><head><meta charset='utf-8'>"
         "<link href='https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&family=Roboto:wght@400;500;700"
         "&family=Roboto+Condensed:wght@400;700&display=swap' rel='stylesheet'>"
         f"<style>{CSS}</style></head><body>"]
    H.append(f"<div class='mast'><div class='vol'>VOL. {F['season']} &nbsp;·&nbsp; ISSUE NO. {wk}</div>"
             f"<div class='title'><span class='e'>🦃</span>{e(F['league'].upper())}<span class='e'>🦃</span></div>"
             "<div class='sub'>WEEKLY NEWSLETTER</div></div><div class='stripe'></div>")
    H.append(f"<div class='band'>WEEK {wk} REVIEW</div>")

    b, c = F["blowout"], F["close"]
    H.append("<div class='pad'><div class='tiles'>"
             f"<div class='tile teal'><div class='l'>👑 TOP SCORE</div><div class='v'>{f2(F['top']['points'])}</div><div class='n'>{e(F['top']['manager'])}</div></div>"
             f"<div class='tile pink'><div class='l'>💩 BOTTOM SCORE</div><div class='v'>{f2(F['bottom']['points'])}</div><div class='n'>{e(F['bottom']['manager'])}</div></div>"
             f"<div class='tile navy'><div class='l'>💥 BLOWOUT</div><div class='v'>{f2(b['margin'])}</div><div class='n'>{e(b['winner'])} over {e(b['loser'])}</div></div>"
             f"<div class='tile gold'><div class='l'>😰 NAIL-BITER</div><div class='v'>{f2(c['margin'])}</div><div class='n'>{e(c['winner'])} over {e(c['loser'])}</div></div>"
             "</div>")
    also = []
    if F["upset"]:
        u = F["upset"]
        also.append(("Biggest upset", f"{e(u['winner'])} (#{u['winner_rank']}) took down {e(u['loser'])} (#{u['loser_rank']})"))
    if F["potw"]:
        also.append(("Player of the week", f"{e(F['potw']['player'])} · {f2(F['potw']['points'])} pts for {e(F['potw']['manager'])}"))
    if F["dud"]:
        also.append(("Biggest dud", f"{e(F['dud']['player'])} · {f2(F['dud']['points'])} pts for {e(F['dud']['manager'])}"))
    bl = F["blunder"]
    if bl["left"] > 0:
        best = f" (best: {e(bl['best']['player'])} ({f2(bl['best']['points'])}))" if bl.get("best") else ""
        also.append(("Bench blunder", f"{e(bl['manager'])} left {f2(bl['left'])} on the bench{best}"))
    H.append("<div class='two'><div><h4>ALSO THIS WEEK</h4><table class='also'>" +
             "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in also) + "</table></div>")
    H.append(f"<div class='box recap'><h4>THE RECAP</h4>{para(T['recap'])}</div>" if T.get("recap") else "<div></div>")
    H.append("</div></div>")

    # game rewind
    pair = split_pair(meta.get("rewind", ""))
    game = next((r for r in F["results"] if pair and {r["winner"], r["loser"]} == set(pair)), None)
    if game:
        wt, lt = F["teams"].get(game["winner"], {}), F["teams"].get(game["loser"], {})
        H.append("<div class='dark pad'><div class='sh'>🏈 GAME REWIND</div><div class='rule'></div>"
                 f"<div class='vs'><div class='side teal'><div class='nm'>{e(game['winner'])}</div><div class='big'>{f2(game['winner_points'])}</div></div>"
                 f"<div class='mid'>DEF</div><div class='side pink r'><div class='nm'>{e(game['loser'])}</div><div class='big'>{f2(game['loser_points'])}</div></div></div>"
                 f"<table class='cmp'><tr><td>{e(wt.get('record') or '')}</td><td>RECORD</td><td>{e(lt.get('record') or '')}</td></tr>"
                 f"<tr><td>+{f2(game['margin'])}</td><td>MARGIN</td><td>-{f2(game['margin'])}</td></tr></table>"
                 f"<div class='foot'>🏆 {e(game['winner'].upper())} won by {f2(game['margin'])}</div>"
                 + (f"<div class='box cream'><h4>WHAT HAPPENED</h4>{para(T['what_happened'])}</div>" if T.get("what_happened") else "")
                 + "</div>")

    # power rankings
    P = F["power"]
    if P:
        ps = [p["power"] for p in P]
        lucks = [p["win_pct"] - p["all_play_pct"] for p in P]
        H.append("<div class='pad'><div class='sh'>🏆 POWER RANKINGS</div><div class='rule'></div><table class='pr'><tr>"
                 "<th>#</th><th>Δ</th><th>Manager</th><th>Record</th><th>Power Score</th><th>Trend</th><th>Win %</th>"
                 "<th>All-Play %</th><th>Luck</th><th>Avg PPG</th></tr>")
        for p in P:
            mv = (f"<span class='up'>▲{p['move']}</span>" if p["move"] > 0 else f"<span class='down'>▼{-p['move']}</span>" if p["move"] < 0 else "")
            luck = p["win_pct"] - p["all_play_pct"]
            H.append(f"<tr><td><b>{p['rank']}</b></td><td>{mv}</td><td>{e(p['manager'])}</td><td>{e(p['record'])}</td>"
                     f"<td style='background:{tint(p['power'], min(ps), max(ps))}'><b>{p['power']:.1f}</b></td><td>{spark(p['scores'])}</td>"
                     f"<td>{p['win_pct'] * 100:.1f}%</td><td>{p['all_play_pct'] * 100:.1f}%</td>"
                     f"<td style='background:{tint(luck, min(lucks), max(lucks))}'>{luck * 100:.1f}%</td><td>{f2(p['ppg'])}</td></tr>")
        H.append("</table>")
        ri, fa = max(P, key=lambda p: p["move"]), min(P, key=lambda p: p["move"])
        H.append("<div class='rf'>" +
                 (f"<span class='up'>▲ RISER &nbsp; {e(ri['manager'])} jumped {ri['move']} spot{'s' if ri['move'] > 1 else ''} to #{ri['rank']}</span>" if ri["move"] > 0 else "<span></span>") +
                 (f"<span class='down'>▼ FALLER &nbsp; {e(fa['manager'])} dropped {-fa['move']} spot{'s' if fa['move'] < -1 else ''} to #{fa['rank']}</span>" if fa["move"] < 0 else "") +
                 "</div></div>")

    # injury report
    if F["injuries"]:
        lst = " &nbsp;·&nbsp; ".join(
            f"<b>{e(m)}:</b> " + ", ".join(f"{e(p)} (<span class='code {'bad' if c in ('D', 'O', 'IR') else ''}'>{c}</span>)" for p, c in pl)
            for m, pl in sorted(F["injuries"].items()))
        H.append("<div class='pad' style='padding-top:4px'><div class='sh'>🚑 INJURY REPORT</div><div class='rule'></div>"
                 f"<div class='injury'><h4>HURTIN' FOR CERTAIN</h4><div class='list'>{lst}</div>"
                 "<div class='k'>Q questionable · D doubtful · O out · IR injured reserve</div>"
                 + (para(T["injuries"]) if T.get("injuries") else "") + "</div></div>")

    # trade talks
    if F["trades"]:
        rows_ = "".join(f"<tr><td>{e(m)} gets</td><td>{e(', '.join(p))}</td></tr>" for t in F["trades"] for m, p in t.items())
        H.append("<div class='pad' style='padding-top:4px'><div class='sh'>🤝 TRADE TALKS</div><div class='rule'></div>"
                 f"<table class='trade'>{rows_}</table>"
                 + (f"<div class='box recap'>{para(T['trade_talk'])}</div>" if T.get("trade_talk") else "") + "</div>")

    # next week's main event
    pair = split_pair(meta.get("main_event", ""))
    if pair and all(x in F["teams"] for x in pair):
        a, b = pair
        ta, tb = F["teams"][a], F["teams"][b]
        status = lambda t: "In the field" if (t.get("seed") or 99) <= F["playoff_teams"] else "Outside looking in"
        H.append(f"<div class='band'>WEEK {nxt} PREVIEW</div>")
        H.append("<div class='dark pad'><div class='sh'>🥊 THE MAIN EVENT</div><div class='rule'></div>"
                 f"<div class='vs'><div class='side teal'><div class='nm big2'>{e(a)}</div>"
                 f"<div class='tag'>POWER RANK #{ta.get('power_rank') or '-'} &nbsp;·&nbsp; {e(ta.get('record') or '')}</div></div>"
                 f"<div class='mid l'>VS</div><div class='side pink r'><div class='nm big2'>{e(b)}</div>"
                 f"<div class='tag'>POWER RANK #{tb.get('power_rank') or '-'} &nbsp;·&nbsp; {e(tb.get('record') or '')}</div></div></div>"
                 "<table class='cmp lg'>"
                 f"<tr><td>#{ta.get('seed') or '-'}</td><td>STANDING</td><td>#{tb.get('seed') or '-'}</td></tr>"
                 f"<tr><td>{f2(ta.get('ppg'))}</td><td>SEASON AVG</td><td>{f2(tb.get('ppg'))}</td></tr>"
                 f"<tr><td>{f2(ta.get('last3'))}</td><td>LAST 3</td><td>{f2(tb.get('last3'))}</td></tr>"
                 + ("" if F["regular_complete"] else f"<tr><td>{status(ta)}</td><td>PLAYOFFS</td><td>{status(tb)}</td></tr>")
                 + f"</table><div class='foot'>{e(series(F, a, b))}</div>"
                 + (f"<div class='box cream g'><h4>THE BREAKDOWN</h4>{para(T['breakdown'])}</div>" if T.get("breakdown") else "")
                 + "</div>")

    # who's wearing the turkey
    tname = F.get("turkey")
    t = F["teams"].get(tname) if tname else None
    if t:
        mv = t.get("move") or 0
        tw = t.get("week") or {}
        this = f"{f2(tw.get('points'))} &nbsp;{tw.get('result', '')} vs {e(tw.get('opponent', ''))}" if tw else "-"
        H.append("<div class='pad'><div class='sh'>🦃 WHO'S WEARING THE TURKEY</div><div class='rule'></div><div class='tk'><div>"
                 f"<table class='ttab'><tr><td>{e(tname)}</td><td>Last place</td></tr>"
                 f"<tr><td>Record</td><td>{e(t.get('record') or '')}</td></tr>"
                 f"<tr><td>Power rank</td><td>#{t.get('power_rank') or '-'} &nbsp;({'no change' if not mv else f'up {mv}' if mv > 0 else f'down {-mv}'})</td></tr>"
                 f"<tr><td>This week</td><td>{this}</td></tr>"
                 f"<tr><td>Season avg</td><td>{f2(t.get('ppg'))}</td></tr>"
                 f"<tr><td>Last 3 avg</td><td>{f2(t.get('last3'))}</td></tr>"
                 f"<tr><td>Bench left</td><td>{f2(tw.get('bench_left')) if tw else '-'}</td></tr></table>"
                 + (f"<h4 style='margin-top:16px'>THE LATEST FROM THE BASEMENT</h4>{para(T['basement'])}" if T.get("basement") else "")
                 + f"</div>{turkey_img(tname)}</div></div>")

    H.append("<div class='stripe rev'></div><div class='wrapup'>THAT'S A WRAP. SEE YOU NEXT WEEK. 🦃</div></body></html>")
    return "".join(H)


def render_all():
    if not OUT.exists():
        return
    tk = b"".join(p.read_bytes() for p in sorted(TURKEY_DIR.glob("*"))) if TURKEY_DIR.exists() else b""
    jobs = []
    for md in sorted(OUT.glob("*-week-*.md")):
        js, jpg, sig = md.with_suffix(".json"), md.with_suffix(".jpg"), md.with_suffix(".sig")
        if not js.exists():
            continue
        h = hashlib.sha256(md.read_bytes() + js.read_bytes() + tk + TEMPLATE_VERSION.encode() + CSS.encode()).hexdigest()
        if jpg.exists() and sig.exists() and sig.read_text().strip() == h:
            continue
        jobs.append((md, js, jpg, sig, h))
    if not jobs:
        print("Newsletter images are up to date.")
        return
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 780, "height": 1000}, device_scale_factor=2)
        for md, js, jpg, sig, h in jobs:
            meta, text = read_md(md)
            page.set_content(render_html(json.loads(js.read_text()), meta, text), wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(300)
            page.screenshot(path=str(jpg), full_page=True, type="jpeg", quality=90)
            sig.write_text(h)
            print(f"Rendered {jpg.name}")
        browser.close()


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--render-only" not in a:
        draft(int(a[a.index("--week") + 1]) if "--week" in a else None, "--force" in a)
    render_all()
