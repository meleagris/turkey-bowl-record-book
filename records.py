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
