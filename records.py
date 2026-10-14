#!/usr/bin/env python3
"""Compute league records from data/league.db and write data/records.json.

Run after sleeper_pull.py. Prints a summary to the log so results are easy to check.
"""
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "league.db"
OUT_PATH = ROOT / "data" / "records.json"
TOP_N = 5
PLAYED_TYPES = ("regular", "playoff", "toilet_bowl")
NON_STARTER_SLOTS = {"BN", "IR", "TAXI"}
SLOT_ELIGIBILITY = {
    "FLEX": {"RB", "WR", "TE"},
    "WRRB_FLEX": {"RB", "WR"},
    "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row
rows = lambda q, *a: [dict(r) for r in con.execute(q, a)]

names = {r["user_id"]: r["name"] for r in rows("SELECT * FROM managers")}
nm = lambda uid: names.get(uid, uid)
r2 = lambda x: round(x, 2) if x is not None else None
players = {r["player_id"]: r for r in rows("SELECT * FROM players")}
pname = lambda pid: (players.get(pid) or {}).get("name") or pid
seasons = {r["season"]: r for r in rows("SELECT * FROM seasons ORDER BY season")}
current_season = max(seasons)


def reg_season_complete(s):
    return s["status"] == "complete" or s["final_through_week"] >= s["playoff_week_start"] - 1


def top(items, key, low=False, n=TOP_N):
    return sorted(items, key=key, reverse=not low)[:n]


# ---------------------------------------------------------------- games

games = rows("SELECT * FROM games WHERE is_final = 1 AND opp_user_id IS NOT NULL "
             "AND game_type IN (?,?,?) ORDER BY season, week", *PLAYED_TYPES)
regular = [g for g in games if g["game_type"] == "regular"]
matchups = [g for g in games if g["roster_id"] < g["opp_roster_id"]]  # one row per game


def game_row(g, **extra):
    return {"season": g["season"], "week": g["week"], "type": g["game_type"],
            "manager": nm(g["user_id"]), "points": r2(g["points"]),
            "opponent": nm(g["opp_user_id"]), "opp_points": r2(g["opp_points"]), **extra}


def matchup_row(g):
    a, b = (g["user_id"], g["points"]), (g["opp_user_id"], g["opp_points"])
    (wu, wp), (lu, lp) = (a, b) if a[1] >= b[1] else (b, a)
    return {"season": g["season"], "week": g["week"], "type": g["game_type"],
            "winner": nm(wu), "winner_points": r2(wp), "loser": nm(lu), "loser_points": r2(lp),
            "margin": r2(wp - lp), "combined": r2(wp + lp)}


mrows = [matchup_row(g) for g in matchups]

# ---------------------------------------------------------------- optimal lineups

starter_slots = {s: [p for p in json.loads(v["roster_positions"] or "[]") if p not in NON_STARTER_SLOTS]
                 for s, v in seasons.items()}
roster_week = defaultdict(list)
for r in rows("SELECT season, week, roster_id, player_id, points FROM player_weeks"):
    pos = (players.get(r["player_id"]) or {}).get("position")
    roster_week[(r["season"], r["week"], r["roster_id"])].append((r["points"] or 0.0, pos, r["player_id"]))


def optimal_points(pool, slots):
    pool = sorted(pool, key=lambda x: x[0], reverse=True)
    used, total = set(), 0.0
    for slot in sorted(slots, key=lambda s: len(SLOT_ELIGIBILITY.get(s, {s}))):
        elig = SLOT_ELIGIBILITY.get(slot, {slot})
        for i, (p, pos, _) in enumerate(pool):
            if i not in used and pos in elig:
                used.add(i)
                total += p
                break
    return total


for g in games:
    opt = optimal_points(roster_week[(g["season"], g["week"], g["roster_id"])], starter_slots[g["season"]])
    g["optimal"] = max(opt, g["points"])
    g["left_on_bench"] = g["optimal"] - g["points"]

# ---------------------------------------------------------------- single game and matchup records

single_game = {
    "highest_score": [game_row(g) for g in top(games, lambda g: g["points"])],
    "lowest_score": [game_row(g) for g in top(games, lambda g: g["points"], low=True)],
    "highest_score_in_loss": [game_row(g) for g in top([g for g in games if g["result"] == "L"], lambda g: g["points"])],
    "lowest_score_in_win": [game_row(g) for g in top([g for g in games if g["result"] == "W"], lambda g: g["points"], low=True)],
    "biggest_blowout": top(mrows, lambda m: m["margin"]),
    "closest_game": top(mrows, lambda m: m["margin"], low=True),
    "highest_combined": top(mrows, lambda m: m["combined"]),
    "lowest_combined": top(mrows, lambda m: m["combined"], low=True),
    "most_points_left_on_bench": [game_row(g, left_on_bench=r2(g["left_on_bench"]), optimal=r2(g["optimal"]))
                                  for g in top(games, lambda g: g["left_on_bench"])],
    "losses_optimal_lineup_would_have_won": [
        game_row(g, optimal=r2(g["optimal"]))
        for g in top([g for g in games if g["result"] == "L" and g["optimal"] > g["opp_points"]],
                     lambda g: g["optimal"] - g["opp_points"], n=50)],
}

# ---------------------------------------------------------------- player records

pw = rows("SELECT pw.*, g.game_type FROM player_weeks pw JOIN games g "
          "ON g.season = pw.season AND g.week = pw.week AND g.roster_id = pw.roster_id "
          "WHERE g.is_final = 1 AND g.game_type IN (?,?,?)", *PLAYED_TYPES)


def player_row(r):
    return {"season": r["season"], "week": r["week"], "manager": nm(r["user_id"]),
            "player": pname(r["player_id"]),
            "position": (players.get(r["player_id"]) or {}).get("position"),
            "points": r2(r["points"]), "slot": r["slot"]}


player_records = {
    "highest_starter_score": [player_row(r) for r in top([r for r in pw if r["is_starter"]], lambda r: r["points"] or 0)],
    "highest_benched_score": [player_row(r) for r in top([r for r in pw if not r["is_starter"]], lambda r: r["points"] or 0)],
}

# ---------------------------------------------------------------- season stats (regular season)

week_scores = defaultdict(list)
for g in regular:
    week_scores[(g["season"], g["week"])].append(g)

season_stats = defaultdict(lambda: defaultdict(float))
for g in regular:
    s = season_stats[(g["season"], g["user_id"])]
    s["games"] += 1
    s[{"W": "wins", "L": "losses", "T": "ties"}[g["result"]]] += 1
    s["pf"] += g["points"]
    s["pa"] += g["opp_points"]
    s["optimal"] += g["optimal"]
    others = [o["points"] for o in week_scores[(g["season"], g["week"])] if o is not g]
    s["ap_wins"] += sum(p < g["points"] for p in others)
    s["ap_losses"] += sum(p > g["points"] for p in others)
    s["ap_ties"] += sum(p == g["points"] for p in others)

weekly_high, weekly_low = defaultdict(int), defaultdict(int)
for (season, week), gs in week_scores.items():
    weekly_high[(season, max(gs, key=lambda g: g["points"])["user_id"])] += 1
    weekly_low[(season, min(gs, key=lambda g: g["points"])["user_id"])] += 1

season_rows = []
for (season, uid), s in season_stats.items():
    ap_games = s["ap_wins"] + s["ap_losses"] + s["ap_ties"]
    ap_pct = (s["ap_wins"] + 0.5 * s["ap_ties"]) / ap_games if ap_games else 0
    win_pct = (s["wins"] + 0.5 * s["ties"]) / s["games"]
    season_rows.append({
        "season": season, "manager": nm(uid), "user_id": uid,
        "complete": reg_season_complete(seasons[season]),
        "record": f"{int(s['wins'])}-{int(s['losses'])}" + (f"-{int(s['ties'])}" if s["ties"] else ""),
        "wins": int(s["wins"]), "win_pct": round(win_pct, 3),
        "points_for": r2(s["pf"]), "points_against": r2(s["pa"]), "ppg": r2(s["pf"] / s["games"]),
        "all_play": f"{int(s['ap_wins'])}-{int(s['ap_losses'])}" + (f"-{int(s['ap_ties'])}" if s["ap_ties"] else ""),
        "all_play_pct": round(ap_pct, 3),
        "luck": round(s["wins"] - ap_pct * s["games"], 2),
        "lineup_efficiency": round(s["pf"] / s["optimal"], 3) if s["optimal"] else None,
        "weekly_high_scores": weekly_high[(season, uid)],
        "weekly_low_scores": weekly_low[(season, uid)],
    })

done = [r for r in season_rows if r["complete"]]
season_records = {
    "most_points_for": top(done, lambda r: r["points_for"]),
    "fewest_points_for": top(done, lambda r: r["points_for"], low=True),
    "most_points_against": top(done, lambda r: r["points_against"]),
    "best_record": top(done, lambda r: (r["win_pct"], r["points_for"])),
    "worst_record": top(done, lambda r: (r["win_pct"], r["points_for"]), low=True),
    "luckiest": top(done, lambda r: r["luck"]),
    "unluckiest": top(done, lambda r: r["luck"], low=True),
    "best_lineup_efficiency": top(done, lambda r: r["lineup_efficiency"] or 0),
    "worst_lineup_efficiency": top(done, lambda r: r["lineup_efficiency"] or 0, low=True),
    "most_weekly_high_scores": top(done, lambda r: r["weekly_high_scores"]),
}

# ---------------------------------------------------------------- season history (brackets)

history = []
finishes = defaultdict(lambda: defaultdict(int))
for season in seasons:
    entry = {"season": season, "champion": None, "runner_up": None, "third": None,
             "turkey": None, "toilet_bowl_opponent": None}
    for b in rows("SELECT * FROM brackets WHERE season = ? AND placement IS NOT NULL", season):
        if not b["winner_user_id"]:
            continue
        if b["bracket"] == "playoff" and b["placement"] == 1:
            entry["champion"], entry["runner_up"] = nm(b["winner_user_id"]), nm(b["loser_user_id"])
            finishes[b["winner_user_id"]]["championships"] += 1
            finishes[b["loser_user_id"]]["runner_ups"] += 1
        elif b["bracket"] == "playoff" and b["placement"] == 3:
            entry["third"] = nm(b["winner_user_id"])
            finishes[b["winner_user_id"]]["thirds"] += 1
        elif b["bracket"] == "toilet_bowl" and b["placement"] == 1:
            # Losers-advance bracket: Sleeper's "winner" here is the team that lost
            # its way to the bottom, which makes them the turkey.
            entry["turkey"] = nm(b["winner_user_id"])
            entry["toilet_bowl_opponent"] = nm(b["loser_user_id"])
            finishes[b["winner_user_id"]]["turkeys"] += 1
    # Sleeper fills the bracket with projected seeds during the season, so only
    # count appearances once the regular season is over.
    appearances = rows("SELECT DISTINCT t1_user_id AS u FROM brackets WHERE season = ? AND bracket = 'playoff' "
                  "UNION SELECT t2_user_id FROM brackets WHERE season = ? AND bracket = 'playoff'", season, season)
    for b in appearances if reg_season_complete(seasons[season]) else []:
        if b["u"]:
            finishes[b["u"]]["playoff_appearances"] += 1
    srows = [r for r in season_rows if r["season"] == season]
    if srows:
        entry["most_points_for"] = max(srows, key=lambda r: r["points_for"])["manager"]
        entry["best_record"] = max(srows, key=lambda r: (r["win_pct"], r["points_for"]))["manager"]
    history.append(entry)

# ---------------------------------------------------------------- streaks

by_mgr = defaultdict(list)
for g in games:
    by_mgr[g["user_id"]].append(g)

streaks = {"longest_win_streak": [], "longest_loss_streak": [], "current": {}}
for uid, gs in by_mgr.items():
    best = {"W": (0, None, None), "L": (0, None, None)}
    run, kind, start = 0, None, None
    for g in gs:
        if g["result"] == kind:
            run += 1
        else:
            run, kind, start = 1, g["result"], g
        if kind in best and run > best[kind][0]:
            best[kind] = (run, start, g)
    for k, key in (("W", "longest_win_streak"), ("L", "longest_loss_streak")):
        n, s, e = best[k]
        if n:
            streaks[key].append({"manager": nm(uid), "length": n,
                                 "from": f"{s['season']} W{s['week']}", "to": f"{e['season']} W{e['week']}"})
    if kind in ("W", "L"):
        streaks["current"][nm(uid)] = f"{kind}{run}"
streaks["longest_win_streak"] = top(streaks["longest_win_streak"], lambda r: r["length"])
streaks["longest_loss_streak"] = top(streaks["longest_loss_streak"], lambda r: r["length"])

# ---------------------------------------------------------------- head to head

h2h = defaultdict(lambda: defaultdict(lambda: {"w": 0, "l": 0, "t": 0, "pf": 0.0, "pa": 0.0}))
for g in games:
    rec = h2h[nm(g["user_id"])][nm(g["opp_user_id"])]
    rec[{"W": "w", "L": "l", "T": "t"}[g["result"]]] += 1
    rec["pf"] += g["points"]
    rec["pa"] += g["opp_points"]
head_to_head = {m: {o: {**v, "pf": r2(v["pf"]), "pa": r2(v["pa"])} for o, v in opps.items()}
                for m, opps in h2h.items()}

# ---------------------------------------------------------------- transactions

bids = rows("SELECT t.season, t.week, t.waiver_bid, m.user_id, m.player_id FROM transactions t "
            "JOIN transaction_moves m USING (transaction_id) WHERE t.type = 'waiver' "
            "AND t.status = 'complete' AND m.action = 'add' AND t.waiver_bid IS NOT NULL")
faab_season = defaultdict(int)
for b in bids:
    faab_season[(b["season"], b["user_id"])] += b["waiver_bid"]
adds_season = defaultdict(int)
for r in rows("SELECT t.season, m.user_id FROM transactions t JOIN transaction_moves m USING (transaction_id) "
              "WHERE t.status = 'complete' AND t.type IN ('waiver','free_agent') AND m.action = 'add'"):
    adds_season[(r["season"], r["user_id"])] += 1
trades = defaultdict(int)
for r in rows("SELECT DISTINCT t.transaction_id, m.user_id FROM transactions t "
              "JOIN transaction_moves m USING (transaction_id) WHERE t.type = 'trade' AND t.status = 'complete'"):
    trades[r["user_id"]] += 1

transaction_records = {
    "biggest_faab_bids": [{"season": b["season"], "week": b["week"], "manager": nm(b["user_id"]),
                           "player": pname(b["player_id"]), "bid": b["waiver_bid"]}
                          for b in top(bids, lambda b: b["waiver_bid"])],
    "most_faab_spent_season": [{"season": s, "manager": nm(u), "spent": v}
                               for (s, u), v in top(faab_season.items(), lambda kv: kv[1])],
    "most_pickups_season": [{"season": s, "manager": nm(u), "pickups": v}
                            for (s, u), v in top(adds_season.items(), lambda kv: kv[1])],
}

# ---------------------------------------------------------------- all-time manager table

managers = []
for uid in {g["user_id"] for g in games}:
    mine = [r for r in season_rows if r["user_id"] == uid]
    reg = [g for g in regular if g["user_id"] == uid]
    po = [g for g in games if g["user_id"] == uid and g["game_type"] == "playoff"]
    w = sum(g["result"] == "W" for g in reg)
    l = sum(g["result"] == "L" for g in reg)
    t = sum(g["result"] == "T" for g in reg)
    pf = sum(g["points"] for g in reg)
    ap_w = sum(int(r["all_play"].split("-")[0]) for r in mine)
    ap_l = sum(int(r["all_play"].split("-")[1]) for r in mine)
    f = finishes[uid]
    managers.append({
        "manager": nm(uid), "seasons": len(mine),
        "record": f"{w}-{l}" + (f"-{t}" if t else ""),
        "win_pct": round((w + 0.5 * t) / len(reg), 3) if reg else 0,
        "points_for": r2(pf), "points_against": r2(sum(g["opp_points"] for g in reg)),
        "ppg": r2(pf / len(reg)) if reg else 0,
        "all_play_pct": round(ap_w / (ap_w + ap_l), 3) if ap_w + ap_l else 0,
        "playoff_record": f"{sum(g['result'] == 'W' for g in po)}-{sum(g['result'] == 'L' for g in po)}",
        "playoff_appearances": f["playoff_appearances"], "championships": f["championships"],
        "runner_ups": f["runner_ups"], "thirds": f["thirds"], "turkeys": f["turkeys"],
        "weekly_high_scores": sum(r["weekly_high_scores"] for r in mine),
        "trades": trades[uid],
    })
managers.sort(key=lambda m: (m["championships"], m["win_pct"]), reverse=True)

# ---------------------------------------------------------------- season detail (the Record Book's per-season pages)

import math
import random
import statistics

RAW = ROOT / "data" / "raw"
CONFIG = {
    # dollars for each regular season weekly high score; seasons not listed use "default"
    "weekly_prize": {"default": 5, "2025": 0},
    "power_weights": {"ppg": 2, "last3": 4, "win": 2, "all_play": 2},
    "odds_sims": 3000,
}


def load_raw(*parts, default=None):
    p = RAW.joinpath(*parts)
    return json.loads(p.read_text()) if p.exists() else default


def round_weeks(r, pws, round_type, total):
    if round_type == 2:
        start = pws + 2 * (r - 1)
        return [start, start + 1]
    start = pws + (r - 1)
    return [start, start + 1] if round_type == 1 and r == total else [start]


def round_name(b, max_r):
    if b["bracket"] == "toilet_bowl":
        return "Toilet Bowl final" if b["placement"] == 1 else "Toilet Bowl"
    p = b["placement"]
    if p == 1:
        return "Championship"
    if p == 3:
        return "Third place"
    if p:
        return "Consolation"
    if b["round"] == max_r - 1:
        return "Semifinal"
    if b["round"] == max_r - 2:
        return "Quarterfinal"
    return "Round 1"


# Avatars: the team picture each manager uses on Sleeper, most recent season wins.
avatars = {}
for season in sorted(seasons):
    for u in load_raw(season, "users.json", default=[]) or []:
        meta = u.get("metadata") or {}
        url = meta.get("avatar") or (f"https://sleepercdn.com/avatars/thumbs/{u['avatar']}" if u.get("avatar") else None)
        if url:
            avatars[nm(u["user_id"])] = url

score_of = {(g["season"], g["week"], g["user_id"]): g["points"]
            for g in rows("SELECT * FROM games WHERE is_final = 1")}


def power_board(sgames, upto):
    """The Record Book's power score: each input against the league leader, weighted 2/4/2/2."""
    wk = defaultdict(list)
    for g in sgames:
        if g["week"] <= upto:
            wk[g["week"]].append(g)
    t = defaultdict(lambda: {"pts": [], "w": 0.0, "g": 0, "apw": 0.0, "apg": 0})
    for w in sorted(wk):
        for g in wk[w]:
            x = t[g["user_id"]]
            x["pts"].append(g["points"])
            x["g"] += 1
            x["w"] += 1 if g["result"] == "W" else 0.5 if g["result"] == "T" else 0
            others = [o["points"] for o in wk[w] if o is not g]
            x["apw"] += sum(p < g["points"] for p in others) + 0.5 * sum(p == g["points"] for p in others)
            x["apg"] += len(others)
    if not t:
        return []
    vals = {uid: {"ppg": sum(x["pts"]) / x["g"], "last3": sum(x["pts"][-3:]) / len(x["pts"][-3:]),
                  "win": x["w"] / x["g"], "all_play": x["apw"] / x["apg"] if x["apg"] else 0,
                  "wins": x["w"], "games": x["g"]}
            for uid, x in t.items()}
    W = CONFIG["power_weights"]
    mx = {k: max(v[k] for v in vals.values()) for k in W}
    board = []
    for uid, v in vals.items():
        s = sum(W[k] * (v[k] / mx[k] if mx[k] else 0) for k in W) / sum(W.values()) * 100
        board.append({"user_id": uid, "power": s, **v})
    board.sort(key=lambda b: -b["power"])
    return board


def season_detail(season):
    S = seasons[season]
    pws, ptm = S["playoff_week_start"], S["playoff_teams"] or 0
    complete_reg = reg_season_complete(S)
    sg = [g for g in regular if g["season"] == season]
    weeks = sorted({g["week"] for g in sg})
    uids = sorted({r["user_id"] for r in rows("SELECT user_id FROM teams WHERE season = ?", season)}, key=nm)

    # standings
    st = {u: {"user_id": u, "manager": nm(u), "w": 0, "l": 0, "t": 0, "pf": 0.0, "pa": 0.0, "scores": {},
              "optimal": 0.0, "apw": 0, "apl": 0, "apt": 0, "bench": 0.0} for u in uids}
    byweek = defaultdict(list)
    for g in sg:
        byweek[g["week"]].append(g)
    for g in sg:
        x = st[g["user_id"]]
        x[{"W": "w", "L": "l", "T": "t"}[g["result"]]] += 1
        x["pf"] += g["points"]
        x["pa"] += g["opp_points"]
        x["scores"][g["week"]] = g["points"]
        x["optimal"] += g["optimal"]
        x["bench"] += g["left_on_bench"]
        others = [o["points"] for o in byweek[g["week"]] if o is not g]
        x["apw"] += sum(p < g["points"] for p in others)
        x["apl"] += sum(p > g["points"] for p in others)
        x["apt"] += sum(p == g["points"] for p in others)
    table = []
    for x in st.values():
        n = x["w"] + x["l"] + x["t"]
        if not n:
            continue
        sc = list(x["scores"].values())
        apn = x["apw"] + x["apl"] + x["apt"]
        ap_pct = (x["apw"] + 0.5 * x["apt"]) / apn if apn else 0
        table.append({
            "manager": x["manager"], "user_id": x["user_id"],
            "record": f"{x['w']}-{x['l']}" + (f"-{x['t']}" if x["t"] else ""),
            "win_pct": round((x["w"] + 0.5 * x["t"]) / n, 3),
            "pf": r2(x["pf"]), "pa": r2(x["pa"]), "diff": r2(x["pf"] - x["pa"]), "ppg": r2(x["pf"] / n),
            "high": r2(max(sc)), "low": r2(min(sc)), "sd": r2(statistics.stdev(sc)) if len(sc) > 1 else 0,
            "all_play": f"{x['apw']}-{x['apl']}" + (f"-{x['apt']}" if x["apt"] else ""), "all_play_pct": round(ap_pct, 3),
            "luck": round(x["w"] + 0.5 * x["t"] - ap_pct * n, 2),
            "lineup_efficiency": round(x["pf"] / x["optimal"], 3) if x["optimal"] else None,
            "bench_points": r2(x["bench"]),
            "scores": [r2(x["scores"].get(w)) for w in weeks],
        })
    table.sort(key=lambda r: (r["win_pct"], r["pf"]), reverse=True)
    for i, r in enumerate(table):
        r["seed"] = i + 1
    by_uid = {r["user_id"]: r for r in table}

    # brackets with round names and scores
    br = rows("SELECT * FROM brackets WHERE season = ? ORDER BY bracket, round, match", season)
    max_r = {b: max((x["round"] for x in br if x["bracket"] == b), default=0) for b in ("playoff", "toilet_bowl")}
    brackets = []
    for b in br:
        wks = round_weeks(b["round"], pws, S["playoff_round_type"], max_r[b["bracket"]])
        def sc(u):
            vals = [score_of.get((season, w, u)) for w in wks]
            return r2(sum(v for v in vals if v is not None)) if u and any(v is not None for v in vals) else None
        brackets.append({"bracket": b["bracket"], "round": b["round"], "name": round_name(b, max_r[b["bracket"]]),
                         "week": wks[0], "t1": nm(b["t1_user_id"]) if b["t1_user_id"] else None,
                         "t2": nm(b["t2_user_id"]) if b["t2_user_id"] else None,
                         "s1": sc(b["t1_user_id"]), "s2": sc(b["t2_user_id"]),
                         "winner": nm(b["winner_user_id"]) if b["winner_user_id"] else None,
                         "_w": b["winner_user_id"], "_l": b["loser_user_id"], "_p": b["placement"],
                         "_t": [b["t1_user_id"], b["t2_user_id"]]})

    champ = runner = third = turkey = None
    for b in brackets:
        if b["bracket"] == "playoff" and b["_p"] == 1 and b["_w"]:
            champ, runner = b["_w"], b["_l"]
        if b["bracket"] == "playoff" and b["_p"] == 3 and b["_w"]:
            third = b["_w"]
        if b["bracket"] == "toilet_bowl" and b["_p"] == 1 and b["_w"]:
            turkey = b["_w"]   # losers-advance: Sleeper's "winner" of the final is the turkey
    if champ and not third:
        # No third-place game (Art. 11.5): the better seed of the two beaten semifinalists.
        beaten = [b["_l"] for b in brackets if b["name"] == "Semifinal" and b["_l"]]
        beaten.sort(key=lambda u: by_uid[u]["seed"] if u in by_uid else 99)
        third = beaten[0] if beaten else None
    in_playoffs = {u for b in brackets if b["bracket"] == "playoff" for u in b["_t"] if u} if complete_reg else set()
    order = [r["user_id"] for r in table]
    if champ:
        fixed = [u for u in (champ, runner, third) if u]
        rest = [u for u in order if u not in fixed and u != turkey]
        final = fixed + rest + ([turkey] if turkey else [])
    else:
        final = order
    for i, u in enumerate(final):
        if u in by_uid:
            by_uid[u]["place"] = i + 1
            by_uid[u]["made_playoffs"] = u in in_playoffs
    for b in brackets:
        for k in ("_w", "_l", "_p", "_t"):
            b.pop(k)

    # power boards by week (for awards and the current power rankings)
    boards = {w: power_board(sg, w) for w in weeks}

    # weekly high scores and the prize
    highs, prize = [], defaultdict(float)
    for w in weeks:
        gs = byweek[w]
        topv = max(g["points"] for g in gs)
        win = [g["user_id"] for g in gs if g["points"] == topv]
        highs.append({"week": w, "managers": [nm(u) for u in win], "points": r2(topv)})
        for u in win:
            prize[u] += 1 / len(win)
    prize_amt = CONFIG["weekly_prize"].get(season, CONFIG["weekly_prize"]["default"])
    prize_tally = sorted([{"manager": nm(u), "weeks": round(n, 2), "dollars": round(n * prize_amt, 2)}
                          for u, n in prize.items()], key=lambda r: -r["weeks"]) if prize_amt else []

    # awards
    awards = []
    def add(label, who, val, detail=""):
        if who:
            awards.append({"label": label, "who": who, "value": val, "detail": detail})
    if table:
        cells = [(g["points"], g) for g in sg]
        hi = max(cells, key=lambda c: c[0])[1]; lo = min(cells, key=lambda c: c[0])[1]
        add("Highest score, single week", nm(hi["user_id"]), r2(hi["points"]), f"Week {hi['week']}")
        add("Lowest score, single week", nm(lo["user_id"]), r2(lo["points"]), f"Week {lo['week']}")
        a = max(table, key=lambda r: r["ppg"]); add("Highest scoring average", a["manager"], a["ppg"], "Points per game")
        ms = [g for g in sg if g["roster_id"] < g["opp_roster_id"]]
        if ms:
            bl = max(ms, key=lambda g: abs(g["points"] - g["opp_points"]))
            cl = min(ms, key=lambda g: abs(g["points"] - g["opp_points"]))
            for label, g in (("Biggest blowout", bl), ("Closest game", cl)):
                wu, lu = (g["user_id"], g["opp_user_id"]) if g["points"] >= g["opp_points"] else (g["opp_user_id"], g["user_id"])
                add(label, nm(wu), r2(abs(g["points"] - g["opp_points"])), f"Week {g['week']} over {nm(lu)}")
        a = max(table, key=lambda r: r["all_play_pct"]); add("Best all-play record", a["manager"], a["all_play"], "Record against the whole league every week")
        a = max(table, key=lambda r: r["luck"]); add("Luckiest team", a["manager"], f"{a['luck']:+.1f} wins", "Wins above what the scores earned")
        a = min(table, key=lambda r: r["luck"]); add("Unluckiest team", a["manager"], f"{a['luck']:+.1f} wins", "Wins below what the scores earned")
        tops, top3 = defaultdict(int), defaultdict(int)
        for w, b in boards.items():
            if b:
                tops[b[0]["user_id"]] += 1
            for x in b[:3]:
                top3[x["user_id"]] += 1
        if tops:
            u = max(tops, key=tops.get); add("Most weeks at #1", nm(u), tops[u], "Weeks holding the top power ranking")
            u = max(top3, key=top3.get); add("Most weeks in the top 3", nm(u), top3[u], "Weeks ranked 3rd or better")
        if prize:
            u = max(prize, key=prize.get); add("Most weekly high scores", nm(u), round(prize[u], 1), "Weeks outscoring every other team")
        multi = [r for r in table if len([s for s in r["scores"] if s is not None]) > 1]
        if multi:
            a = min(multi, key=lambda r: r["sd"]); add("Most consistent", a["manager"], a["sd"], "Smallest week-to-week swing")
            a = max(multi, key=lambda r: r["sd"]); add("Most volatile", a["manager"], a["sd"], "Biggest week-to-week swing")
        a = max(table, key=lambda r: r["lineup_efficiency"] or 0); add("Best lineup setter", a["manager"], f"{a['lineup_efficiency'] * 100:.1f}%", "Points scored out of the most possible")
        a = max(table, key=lambda r: r["bench_points"]); add("Most points left on the bench", a["manager"], a["bench_points"], "Season total")
        totals = {w: sum(g["points"] for g in byweek[w]) for w in weeks}
        w = max(totals, key=totals.get); add("Highest scoring week, league-wide", "Whole league", r2(totals[w]), f"Week {w}")
        w = min(totals, key=totals.get); add("Lowest scoring week, league-wide", "Whole league", r2(totals[w]), f"Week {w}")

    # every matchup, playoffs included, one row per game
    names_by_week = defaultdict(dict)
    for b in brackets:
        for t in (b["t1"], b["t2"]):
            if t:
                names_by_week[b["week"]][t] = b["name"]
    matchups_out = []
    for g in games:
        if g["season"] != season or g["roster_id"] > g["opp_roster_id"]:
            continue
        a_w = g["points"] >= g["opp_points"]
        matchups_out.append({
            "week": g["week"], "type": g["game_type"], "round": names_by_week[g["week"]].get(nm(g["user_id"])),
            "winner": nm(g["user_id"] if a_w else g["opp_user_id"]), "winner_points": r2(max(g["points"], g["opp_points"])),
            "loser": nm(g["opp_user_id"] if a_w else g["user_id"]), "loser_points": r2(min(g["points"], g["opp_points"])),
            "tie": g["points"] == g["opp_points"]})
    matchups_out.sort(key=lambda m: (m["week"], -m["winner_points"]))

    # draft board
    dr = rows("SELECT * FROM draft_picks WHERE season = ? ORDER BY pick_no", season)
    draft = None
    if dr:
        did = max({p["draft_id"] for p in dr}, key=lambda d: sum(p["draft_id"] == d for p in dr))
        dr = [p for p in dr if p["draft_id"] == did]
        r1 = sorted([p for p in dr if p["round"] == 1], key=lambda p: p["pick_no"])
        draft = {"order": [nm(p["user_id"]) for p in r1],
                 "picks": [{"round": p["round"], "pick": p["pick_no"], "manager": nm(p["user_id"]),
                            "player": pname(p["player_id"]),
                            "position": (players.get(p["player_id"]) or {}).get("position"),
                            "team": (players.get(p["player_id"]) or {}).get("team"),
                            "keeper": bool(p["is_keeper"])} for p in dr]}

    for r in table:
        r.pop("user_id")
    return {
        "season": season, "status": S["status"], "complete": bool(champ), "regular_complete": complete_reg,
        "playoff_week_start": pws, "playoff_teams": ptm, "weeks": weeks,
        "champion": nm(champ) if champ else None, "runner_up": nm(runner) if runner else None,
        "third": nm(third) if third else None, "turkey": nm(turkey) if turkey else None,
        "standings": table, "brackets": brackets, "awards": awards, "weekly_high_scores": highs,
        "weekly_prize": prize_amt, "prize_tally": prize_tally, "matchups": matchups_out, "draft": draft,
        "_boards": boards, "_final": final, "_complete": bool(champ),
    }


season_details = {s: season_detail(s) for s in seasons}

# ---------------------------------------------------------------- current season: power, playoff picture, odds

cur = season_details[current_season]
power = []
if cur["weeks"]:
    upto = cur["weeks"][-1]
    board = cur["_boards"][upto]
    prev = {b["user_id"]: i + 1 for i, b in enumerate(cur["_boards"].get(upto - 1, []))}
    trend_scores = {r["manager"]: r["scores"] for r in cur["standings"]}
    for i, b in enumerate(board):
        rank_hist = []
        for w in cur["weeks"]:
            pos = next((j + 1 for j, x in enumerate(cur["_boards"][w]) if x["user_id"] == b["user_id"]), None)
            rank_hist.append(pos)
        power.append({"rank": i + 1, "manager": nm(b["user_id"]),
                      "move": (prev[b["user_id"]] - (i + 1)) if b["user_id"] in prev else 0,
                      "power": round(b["power"], 1), "ppg": r2(b["ppg"]), "last3": r2(b["last3"]),
                      "win_pct": round(b["win"], 3), "all_play_pct": round(b["all_play"], 3),
                      "record": next(r["record"] for r in cur["standings"] if r["manager"] == nm(b["user_id"])),
                      "scores": trend_scores.get(nm(b["user_id"]), []), "ranks": rank_hist})


def playoff_odds():
    S = seasons[current_season]
    if cur["regular_complete"] or not cur["weeks"]:
        return {}
    pws, ptm = S["playoff_week_start"], S["playoff_teams"] or 6
    owner = {r["roster_id"]: r["user_id"] for r in rows("SELECT * FROM teams WHERE season = ?", current_season)}
    sg = [g for g in regular if g["season"] == current_season]
    allpts = [g["points"] for g in sg]
    lg = sum(allpts) / len(allpts)
    team = {}
    for u in {g["user_id"] for g in sg}:
        pts = [g["points"] for g in sg if g["user_id"] == u]
        n = len(pts)
        mean = (sum(pts) + lg * 4) / (n + 4)   # two good weeks are not proof
        sd = statistics.stdev(pts) if n > 1 else mean * 0.22
        wins = sum(1 if g["result"] == "W" else 0.5 if g["result"] == "T" else 0 for g in sg if g["user_id"] == u)
        team[u] = {"mean": mean, "sd": max(sd, mean * 0.16), "w": wins, "pf": sum(pts)}
    fixtures = []
    for w in range(cur["weeks"][-1] + 1, pws):
        groups = defaultdict(list)
        for e in load_raw(current_season, "matchups", f"{w:02d}.json", default=[]) or []:
            if e.get("matchup_id") is not None:
                groups[e["matchup_id"]].append(owner.get(e["roster_id"]))
        for g in groups.values():
            if len(g) == 2 and all(u in team for u in g):
                fixtures.append((w, g[0], g[1]))
    if not fixtures:
        return {}
    rng = random.Random(20260923)
    us = list(team)
    made, bye, first = defaultdict(int), defaultdict(int), defaultdict(int)
    byes = 2 ** math.ceil(math.log2(ptm)) - ptm if ptm > 1 else 0
    sims = CONFIG["odds_sims"]
    for _ in range(sims):
        wins = {u: team[u]["w"] for u in us}
        pf = {u: team[u]["pf"] for u in us}
        cw, score = None, {}
        for w, a, b in fixtures:
            if w != cw:
                cw = w
                score = {u: max(30, rng.gauss(team[u]["mean"], team[u]["sd"])) for u in us}
            pf[a] += score[a]; pf[b] += score[b]
            if score[a] > score[b]:
                wins[a] += 1
            elif score[b] > score[a]:
                wins[b] += 1
        order = sorted(us, key=lambda u: (wins[u], pf[u]), reverse=True)
        for i, u in enumerate(order):
            if i < ptm: made[u] += 1
            if i < byes: bye[u] += 1
            if i == 0: first[u] += 1
    return {nm(u): {"make": round(made[u] / sims, 3), "bye": round(bye[u] / sims, 3) if byes else None,
                    "first": round(first[u] / sims, 3)} for u in us}


odds = playoff_odds()
last_week = None
if cur["weeks"]:
    w = cur["weeks"][-1]
    gs = sorted([g for g in regular if g["season"] == current_season and g["week"] == w], key=lambda g: -g["points"])
    last_week = {"week": w, "top": [{"manager": nm(g["user_id"]), "points": r2(g["points"])} for g in gs[:3]]}

# ---------------------------------------------------------------- all-time extras

done_seasons = [s for s in sorted(seasons) if season_details[s]["_complete"]]
finishes = {}
for s in done_seasons:
    d = season_details[s]
    for r in d["standings"]:
        finishes.setdefault(r["manager"], {})[s] = {"place": r.get("place"), "title": r["manager"] == d["champion"],
                                                    "turkey": r["manager"] == d["turkey"], "playoffs": r.get("made_playoffs", False)}
finish_rows = []
for m, by in finishes.items():
    places = [v["place"] for v in by.values() if v["place"]]
    finish_rows.append({"manager": m, "seasons": by, "avg": round(sum(places) / len(places), 2) if places else None})
finish_rows.sort(key=lambda r: r["avg"] or 99)

post = defaultdict(lambda: {"g": 0, "w": 0, "pts": 0.0})
for g in games:
    if g["game_type"] == "playoff":
        x = post[g["user_id"]]
        x["g"] += 1; x["w"] += g["result"] == "W"; x["pts"] += g["points"]

career = defaultdict(lambda: {"hi": None, "lo": None})
for g in games:
    c = career[g["user_id"]]
    c["hi"] = g["points"] if c["hi"] is None else max(c["hi"], g["points"])
    c["lo"] = g["points"] if c["lo"] is None else min(c["lo"], g["points"])
uid_by_name = {nm(u): u for u in names}
for m in managers:
    u = uid_by_name.get(m["manager"])
    p = post[u]
    m.update({"playoff_games": p["g"], "playoff_wins": p["w"],
              "playoff_win_pct": round(p["w"] / p["g"], 3) if p["g"] else None,
              "playoff_points": r2(p["pts"]), "playoff_ppg": r2(p["pts"] / p["g"]) if p["g"] else None,
              "career_high": r2(career[u]["hi"]), "career_low": r2(career[u]["lo"]),
              "avg_finish": next((f["avg"] for f in finish_rows if f["manager"] == m["manager"]), None)})

# runs: best, worst and current, playoffs included, in the order the games were played
runs = []
for uid, gs in by_mgr.items():
    best = worst = cur_run = 0
    for g in gs:
        v = 1 if g["result"] == "W" else -1 if g["result"] == "L" else 0
        cur_run = (cur_run + 1 if cur_run > 0 else 1) if v > 0 else (cur_run - 1 if cur_run < 0 else -1) if v < 0 else 0
        best, worst = max(best, cur_run), min(worst, cur_run)
    runs.append({"manager": nm(uid), "games": len(gs), "best": best, "worst": -worst,
                 "now": f"W{cur_run}" if cur_run > 0 else f"L{-cur_run}" if cur_run < 0 else "-"})
runs.sort(key=lambda r: -r["best"])

# rivalries: the pairs who have played most, and how one-sided it has been
pairs = {}
for g in matchups:
    a, b = sorted([g["user_id"], g["opp_user_id"]], key=nm)
    p = pairs.setdefault((a, b), {"a": nm(a), "b": nm(b), "games": 0, "a_wins": 0, "b_wins": 0, "ties": 0, "margin": 0.0, "biggest": None})
    pa = g["points"] if g["user_id"] == a else g["opp_points"]
    pb = g["opp_points"] if g["user_id"] == a else g["points"]
    p["games"] += 1
    p["a_wins"] += pa > pb; p["b_wins"] += pb > pa; p["ties"] += pa == pb
    p["margin"] += abs(pa - pb)
    if not p["biggest"] or abs(pa - pb) > p["biggest"]["margin"]:
        p["biggest"] = {"winner": nm(a) if pa >= pb else nm(b), "margin": r2(abs(pa - pb)), "season": g["season"], "week": g["week"]}
rivals = sorted(pairs.values(), key=lambda p: (-p["games"], -abs(p["a_wins"] - p["b_wins"])))[:10]
for p in rivals:
    p["avg_margin"] = r2(p.pop("margin") / p["games"])

# draft position history
draft_history = {s: season_details[s]["draft"]["order"] for s in sorted(seasons) if season_details[s]["draft"]}

# ---------------------------------------------------------------- keepers (Constitution art. 7)

def keeper_ledger():
    rosters = load_raw(current_season, "rosters.json", default=[]) or []
    picks = defaultdict(dict)      # player -> season -> pick
    for p in rows("SELECT * FROM draft_picks"):
        picks[p["player_id"]][p["season"]] = p
    out = []
    for r in rosters:
        uid = r.get("owner_id")
        if not uid:
            continue
        for pid in r.get("players") or []:
            hist = picks.get(pid, {})
            pick = hist.get(current_season)
            yrs, orig = 0, None
            if pick:
                s = current_season
                while pick and pick["is_keeper"]:
                    yrs += 1
                    s = str(int(s) - 1)
                    pick = hist.get(s)
                orig = pick["round"] if pick else None
            undrafted = orig is None and not yrs
            cost = (5 - yrs) if undrafted else (orig - 1 - yrs if orig else None)
            if yrs >= 2:
                status = "Max years kept"
            elif cost is None or cost <= 1:
                status = "Not keepable"
            else:
                status = f"Round {cost}"
            pl = players.get(pid) or {}
            out.append({"manager": nm(uid), "player": pname(pid), "position": pl.get("position"), "team": pl.get("team"),
                        "drafted": f"Round {orig}" if orig else "Undrafted", "years_kept": yrs,
                        "cost": cost if status.startswith("Round") else None, "status": status})
    out.sort(key=lambda x: (x["manager"], x["cost"] or 99))
    return out


keepers = keeper_ledger()

# patch the history with the third-place fallback, then strip private keys
for h in history:
    d = season_details[h["season"]]
    if d["complete"] and not h["third"]:
        h["third"] = d["third"]
    hi = max((g for g in games if g["season"] == h["season"]), key=lambda g: g["points"], default=None)
    h["high_score"] = {"manager": nm(hi["user_id"]), "points": r2(hi["points"]), "week": hi["week"]} if hi else None
for d in season_details.values():
    for k in ("_boards", "_final", "_complete"):
        d.pop(k)


# ---------------------------------------------------------------- output

records = {
    "generated_through": {"season": current_season, "week": seasons[current_season]["final_through_week"]},
    "history": history,
    "managers": managers,
    "current_season": sorted([r for r in season_rows if r["season"] == current_season],
                             key=lambda r: (r["win_pct"], r["points_for"]), reverse=True),
    "single_game": single_game,
    "season": season_records,
    "players": player_records,
    "streaks": streaks,
    "transactions": transaction_records,
    "head_to_head": head_to_head,
    "avatars": avatars,
    "seasons": [season_details[s] for s in sorted(seasons, reverse=True)],
    "power": power,
    "playoff_odds": odds,
    "last_week": last_week,
    "finishes": {"seasons": done_seasons, "rows": finish_rows},
    "runs": runs,
    "rivals": rivals,
    "draft_history": draft_history,
    "keepers": keepers,
    "config": {"power_weights": CONFIG["power_weights"]},
}
OUT_PATH.write_text(json.dumps(records, indent=1))

print("SEASON HISTORY")
for h in history:
    if not h["champion"]:
        print(f"  {h['season']}: in progress")
        continue
    print(f"  {h['season']}: champ {h['champion']}, runner-up {h['runner_up']}, 3rd {h['third']}, "
          f"turkey {h['turkey']} (toilet bowl final vs {h['toilet_bowl_opponent']})")
print("\nALL-TIME (regular season)")
for m in managers:
    print(f"  {m['manager']:<12} {m['record']:<7} PF {m['points_for']:<8} titles {m['championships']}  "
          f"playoffs {m['playoff_appearances']}  turkeys {m['turkeys']}  high scores {m['weekly_high_scores']}")
print("\nTOP RECORDS")
for label, lst, fmt in [
    ("Highest score", single_game["highest_score"], lambda r: f"{r['manager']} {r['points']} ({r['season']} W{r['week']})"),
    ("Lowest score", single_game["lowest_score"], lambda r: f"{r['manager']} {r['points']} ({r['season']} W{r['week']})"),
    ("Biggest blowout", single_game["biggest_blowout"], lambda r: f"{r['winner']} over {r['loser']} by {r['margin']} ({r['season']} W{r['week']})"),
    ("Closest game", single_game["closest_game"], lambda r: f"{r['winner']} over {r['loser']} by {r['margin']} ({r['season']} W{r['week']})"),
    ("Most left on bench", single_game["most_points_left_on_bench"], lambda r: f"{r['manager']} {r['left_on_bench']} ({r['season']} W{r['week']})"),
    ("Best player game", player_records["highest_starter_score"], lambda r: f"{r['player']} {r['points']} for {r['manager']} ({r['season']} W{r['week']})"),
    ("Longest win streak", streaks["longest_win_streak"], lambda r: f"{r['manager']} {r['length']} ({r['from']} to {r['to']})"),
]:
    print(f"  {label}: {fmt(lst[0]) if lst else 'n/a'}")
print(f"\nWrote {OUT_PATH.relative_to(ROOT)}")
