#!/usr/bin/env python3
"""Pull a Sleeper league's full history and build a SQLite database from it.

Usage:
  python sleeper_pull.py            fetch new data from Sleeper, then rebuild data/league.db
  python sleeper_pull.py --offline  rebuild data/league.db from the saved raw files only

Outputs:
  data/raw/<season>/...   permanent copy of everything Sleeper returned (commit this)
  data/league.db          SQLite database, rebuilt from the raw files every run
  managers.json           Sleeper user ID -> manager name (set real names once)
"""
import json
import math
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CONFIG = {
    # Any season of the league works. The script walks back through previous
    # seasons, and forward into renewed seasons, on its own.
    "league_id": "1312615826846654464",
    # Only used to find next season's league automatically once it renews.
    "sleeper_username": "meleagris",
}

API = "https://api.sleeper.app/v1"
ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "league.db"
MANAGERS_PATH = ROOT / "managers.json"
LEAGUES_PATH = RAW / "leagues.json"
MAX_WEEKS = 18
FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}
NON_STARTER_SLOTS = {"BN", "IR", "TAXI"}
PLAYERS_MAX_AGE = 20 * 3600  # Sleeper asks that /players/nfl be called at most daily


# ---------------------------------------------------------------- helpers

def get(path, retries=4):
    url = f"{API}/{path}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "league-record-book/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True))


def load(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def pts(settings, key):
    if key not in settings:
        return None
    return settings[key] + settings.get(f"{key}_decimal", 0) / 100


# ---------------------------------------------------------------- fetching

def find_renewal(league, user_id):
    next_season = str(int(league["season"]) + 1)
    for lg in get(f"user/{user_id}/leagues/nfl/{next_season}") or []:
        if lg.get("previous_league_id") == league["league_id"]:
            return lg
    return None


def fetch_all():
    state = get("state/nfl")
    save(RAW / "nfl_state.json", state)

    newest = get(f"league/{CONFIG['league_id']}")
    if not newest:
        sys.exit("League not found. Check league_id in CONFIG.")

    user = get(f"user/{CONFIG['sleeper_username']}") if CONFIG.get("sleeper_username") else None
    if user:
        while (newer := find_renewal(newest, user["user_id"])):
            print(f"Found renewed league for {newer['season']}")
            newest = newer

    leagues, lg = {}, newest
    while lg:
        leagues[lg["season"]] = lg
        prev = lg.get("previous_league_id")
        lg = get(f"league/{prev}") if prev and prev != "0" else None

    save(LEAGUES_PATH, {s: l["league_id"] for s, l in sorted(leagues.items())})
    for season in sorted(leagues):
        fetch_season(leagues[season])
    fetch_players()


def fetch_season(league):
    season, lid = league["season"], league["league_id"]
    d = RAW / season
    complete = league.get("status") == "complete"
    if complete and (d / "_complete").exists():
        print(f"{season}: complete and saved, skipping")
        return

    print(f"{season}: fetching")
    save(d / "league.json", league)
    save(d / "users.json", get(f"league/{lid}/users") or [])
    save(d / "rosters.json", get(f"league/{lid}/rosters") or [])
    save(d / "winners_bracket.json", get(f"league/{lid}/winners_bracket") or [])
    save(d / "losers_bracket.json", get(f"league/{lid}/losers_bracket") or [])
    save(d / "traded_picks.json", get(f"league/{lid}/traded_picks") or [])
    # Every week is refetched until the season is complete, so stat corrections flow in.
    for wk in range(1, MAX_WEEKS + 1):
        save(d / "matchups" / f"{wk:02d}.json", get(f"league/{lid}/matchups/{wk}") or [])
        save(d / "transactions" / f"{wk:02d}.json", get(f"league/{lid}/transactions/{wk}") or [])
    drafts = get(f"league/{lid}/drafts") or []
    save(d / "drafts.json", drafts)
    for dr in drafts:
        save(d / "draft_picks" / f"{dr['draft_id']}.json", get(f"draft/{dr['draft_id']}/picks") or [])

    if complete:
        (d / "_complete").write_text(time.strftime("%Y-%m-%d"))


def fetch_players():
    path = RAW / "players.json"
    cached = load(path, {})
    fresh = time.time() - cached.get("fetched", 0) < PLAYERS_MAX_AGE
    has_injuries = all(len(v) >= 4 for v in list(cached.get("players", {}).values())[:50])
    if fresh and has_injuries:
        return
    print("players: fetching")
    slim = {}
    for pid, p in (get("players/nfl") or {}).items():
        pos = p.get("position")
        if pos not in FANTASY_POSITIONS:
            continue
        name = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        slim[pid] = [name, pos, p.get("team"), p.get("injury_status")]
    save(path, {"fetched": int(time.time()), "players": slim})


# ---------------------------------------------------------------- database

SCHEMA = """
CREATE TABLE seasons (season TEXT PRIMARY KEY, league_id TEXT, name TEXT, status TEXT,
  num_teams INTEGER, playoff_week_start INTEGER, playoff_teams INTEGER,
  playoff_round_type INTEGER, median_game INTEGER, final_through_week INTEGER,
  roster_positions TEXT, scoring_settings TEXT);
CREATE TABLE managers (user_id TEXT PRIMARY KEY, name TEXT);
CREATE TABLE teams (season TEXT, roster_id INTEGER, user_id TEXT, team_name TEXT,
  sleeper_display_name TEXT, PRIMARY KEY (season, roster_id));
CREATE TABLE standings (season TEXT, roster_id INTEGER, user_id TEXT, wins INTEGER,
  losses INTEGER, ties INTEGER, points_for REAL, points_against REAL, max_points REAL,
  PRIMARY KEY (season, roster_id));
CREATE TABLE games (season TEXT, week INTEGER, roster_id INTEGER, user_id TEXT, points REAL,
  opp_roster_id INTEGER, opp_user_id TEXT, opp_points REAL, result TEXT, game_type TEXT,
  is_final INTEGER, PRIMARY KEY (season, week, roster_id));
CREATE TABLE player_weeks (season TEXT, week INTEGER, roster_id INTEGER, user_id TEXT,
  player_id TEXT, points REAL, slot TEXT, is_starter INTEGER,
  PRIMARY KEY (season, week, roster_id, player_id));
CREATE TABLE brackets (season TEXT, bracket TEXT, round INTEGER, match INTEGER,
  t1_user_id TEXT, t2_user_id TEXT, winner_user_id TEXT, loser_user_id TEXT, placement INTEGER);
CREATE TABLE transactions (transaction_id TEXT PRIMARY KEY, season TEXT, week INTEGER,
  type TEXT, status TEXT, created INTEGER, creator_user_id TEXT, waiver_bid INTEGER);
CREATE TABLE transaction_moves (transaction_id TEXT, season TEXT, week INTEGER,
  player_id TEXT, action TEXT, roster_id INTEGER, user_id TEXT);
CREATE TABLE transaction_picks (transaction_id TEXT, season TEXT, week INTEGER,
  pick_season TEXT, pick_round INTEGER, original_roster_id INTEGER,
  from_user_id TEXT, to_user_id TEXT);
CREATE TABLE transaction_faab (transaction_id TEXT, season TEXT, week INTEGER,
  from_user_id TEXT, to_user_id TEXT, amount INTEGER);
CREATE TABLE draft_picks (season TEXT, draft_id TEXT, round INTEGER, pick_no INTEGER,
  draft_slot INTEGER, roster_id INTEGER, user_id TEXT, player_id TEXT, is_keeper INTEGER);
CREATE TABLE players (player_id TEXT PRIMARY KEY, name TEXT, position TEXT, team TEXT, injury_status TEXT);
"""


def final_through(league, state):
    """Last week whose scores are final."""
    if league.get("status") == "complete":
        return MAX_WEEKS
    s = league.get("settings") or {}
    if s.get("last_scored_leg"):
        return int(s["last_scored_leg"])
    if state.get("season") == league["season"] and state.get("season_type") == "regular":
        return max(int(state.get("week") or 1) - 1, 0)
    return 0


def round_weeks(r, pws, round_type, total_rounds):
    # round_type 0: one week per round, 1: two-week final, 2: two weeks every round
    if round_type == 2:
        start = pws + 2 * (r - 1)
        return [start, start + 1]
    start = pws + (r - 1)
    return [start, start + 1] if round_type == 1 and r == total_rounds else [start]


def build_season(con, d, state, managers, new_managers):
    league = load(d / "league.json")
    season = league["season"]
    s = league.get("settings") or {}
    users = {u["user_id"]: u for u in load(d / "users.json", [])}
    pws = int(s.get("playoff_week_start") or 15)
    round_type = int(s.get("playoff_round_type") or 0)
    final_wk = final_through(league, state)

    # Last week of the fantasy season (end of the playoffs). Sleeper still scores
    # lineups in later weeks even though no games are played, so those are skipped.
    playoff_teams = int(s.get("playoff_teams") or 0)
    rounds = math.ceil(math.log2(playoff_teams)) if playoff_teams > 1 else 0
    season_end = round_weeks(rounds, pws, round_type, rounds)[-1] if rounds else pws - 1
    season_end = min(season_end, MAX_WEEKS)

    # Teams are keyed by Sleeper user ID, so a manager's history follows them
    # even if they land in a different roster slot from one season to the next.
    owner = {}
    for r in load(d / "rosters.json", []):
        rid = r["roster_id"]
        uid = r.get("owner_id") or f"orphan-{season}-{rid}"
        owner[rid] = uid
        u = users.get(uid, {})
        display = u.get("display_name") or uid
        if uid not in managers:
            managers[uid] = {"name": display, "sleeper_display_name": display}
            new_managers.append(display)
        team_name = (u.get("metadata") or {}).get("team_name") or display
        st = r.get("settings") or {}
        con.execute("INSERT INTO teams VALUES (?,?,?,?,?)", (season, rid, uid, team_name, display))
        con.execute("INSERT INTO standings VALUES (?,?,?,?,?,?,?,?,?)",
                    (season, rid, uid, st.get("wins", 0), st.get("losses", 0), st.get("ties", 0),
                     pts(st, "fpts"), pts(st, "fpts_against"), pts(st, "ppts")))

    con.execute("INSERT INTO seasons VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (season, league["league_id"], league.get("name"), league.get("status"),
                 league.get("total_rosters"), pws, s.get("playoff_teams"), round_type,
                 int(bool(s.get("league_average_match"))), final_wk,
                 json.dumps(league.get("roster_positions")),
                 json.dumps(league.get("scoring_settings"))))

    # Brackets tell us which playoff-week games were real playoff or toilet bowl games.
    bracket_games = {}
    for fname, label in (("winners_bracket", "playoff"), ("losers_bracket", "toilet_bowl")):
        bracket = load(d / f"{fname}.json", []) or []
        total = max((g["r"] for g in bracket), default=0)
        for g in bracket:
            t1, t2 = g.get("t1"), g.get("t2")
            t1 = t1 if isinstance(t1, int) else None
            t2 = t2 if isinstance(t2, int) else None
            con.execute("INSERT INTO brackets VALUES (?,?,?,?,?,?,?,?,?)",
                        (season, label, g["r"], g["m"], owner.get(t1), owner.get(t2),
                         owner.get(g.get("w")), owner.get(g.get("l")), g.get("p")))
            if t1 and t2:
                for wk in round_weeks(g["r"], pws, round_type, total):
                    bracket_games[(wk, frozenset((t1, t2)))] = label

    starter_slots = [p for p in league.get("roster_positions") or [] if p not in NON_STARTER_SLOTS]
    weeks_loaded = 0
    for wk in range(1, season_end + 1):
        entries = load(d / "matchups" / f"{wk:02d}.json", []) or []
        if not entries or all(not e.get("points") for e in entries):
            continue  # unplayed week
        weeks_loaded += 1
        is_final = int(wk <= final_wk)
        by_rid = {e["roster_id"]: e for e in entries}
        opp, gtype = {}, {}
        if wk < pws:
            groups = {}
            for e in entries:
                if e.get("matchup_id") is not None:
                    groups.setdefault(e["matchup_id"], []).append(e["roster_id"])
            for g in groups.values():
                if len(g) == 2:
                    a, b = g
                    opp[a], opp[b] = b, a
                    gtype[a] = gtype[b] = "regular"
        else:
            for (bwk, pair), label in bracket_games.items():
                if bwk == wk:
                    a, b = tuple(pair)
                    opp[a], opp[b] = b, a
                    gtype[a] = gtype[b] = label

        for rid, e in by_rid.items():
            p = e.get("points") or 0.0
            o = opp.get(rid)
            op = by_rid[o].get("points") if o in by_rid else None
            result = None
            if is_final and op is not None:
                result = "W" if p > op else "L" if p < op else "T"
            con.execute("INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (season, wk, rid, owner.get(rid), p, o, owner.get(o), op, result,
                         gtype.get(rid, "none"), is_final))

            slot_of = {}
            for i, pid in enumerate(e.get("starters") or []):
                if pid and pid != "0":
                    slot_of[pid] = starter_slots[i] if i < len(starter_slots) else "START"
            pp = e.get("players_points") or {}
            for pid in e.get("players") or []:
                con.execute("INSERT OR REPLACE INTO player_weeks VALUES (?,?,?,?,?,?,?,?)",
                            (season, wk, rid, owner.get(rid), pid, pp.get(pid, 0.0),
                             slot_of.get(pid, "BN"), int(pid in slot_of)))

    seen = set()
    for wk in range(1, MAX_WEEKS + 1):
        for t in load(d / "transactions" / f"{wk:02d}.json", []) or []:
            tid = t["transaction_id"]
            if tid in seen:
                continue
            seen.add(tid)
            st = t.get("settings") or {}
            con.execute("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?)",
                        (tid, season, wk, t.get("type"), t.get("status"),
                         t.get("created") or t.get("status_updated"), t.get("creator"),
                         st.get("waiver_bid")))
            for key, action in (("adds", "add"), ("drops", "drop")):
                for pid, rid in (t.get(key) or {}).items():
                    con.execute("INSERT INTO transaction_moves VALUES (?,?,?,?,?,?,?)",
                                (tid, season, wk, pid, action, rid, owner.get(rid)))
            for pk in t.get("draft_picks") or []:
                con.execute("INSERT INTO transaction_picks VALUES (?,?,?,?,?,?,?,?)",
                            (tid, season, wk, pk.get("season"), pk.get("round"),
                             pk.get("roster_id"), owner.get(pk.get("previous_owner_id")),
                             owner.get(pk.get("owner_id"))))
            for fb in t.get("waiver_budget") or []:
                con.execute("INSERT INTO transaction_faab VALUES (?,?,?,?,?,?)",
                            (tid, season, wk, owner.get(fb.get("sender")),
                             owner.get(fb.get("receiver")), fb.get("amount")))

    picks_dir = d / "draft_picks"
    if picks_dir.exists():
        for f in sorted(picks_dir.glob("*.json")):
            for p in load(f, []) or []:
                rid = p.get("roster_id")
                con.execute("INSERT INTO draft_picks VALUES (?,?,?,?,?,?,?,?,?)",
                            (season, f.stem, p.get("round"), p.get("pick_no"), p.get("draft_slot"),
                             rid, owner.get(rid) or p.get("picked_by"), p.get("player_id"),
                             int(bool(p.get("is_keeper")))))

    print(f"{season}: {weeks_loaded} weeks loaded, final through week {min(final_wk, weeks_loaded)}")


def build_db():
    leagues = load(LEAGUES_PATH)
    if not leagues:
        sys.exit("No saved data yet. Run without --offline first.")
    state = load(RAW / "nfl_state.json", {})
    managers = load(MANAGERS_PATH, {})
    new_managers = []

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)

    for season in sorted(leagues):
        if (RAW / season / "league.json").exists():
            build_season(con, RAW / season, state, managers, new_managers)

    con.executemany("INSERT INTO managers VALUES (?,?)",
                    [(uid, m["name"]) for uid, m in managers.items()])
    players = load(RAW / "players.json", {}).get("players", {})
    con.executemany("INSERT INTO players VALUES (?,?,?,?,?)",
                    [(pid, *(list(vals) + [None] * 4)[:4]) for pid, vals in players.items()])
    con.commit()
    con.close()

    save(MANAGERS_PATH, managers)
    if new_managers:
        print("\nNew managers added to managers.json with their Sleeper display names:")
        for n in new_managers:
            print(f"  {n}")
        print("Change each \"name\" to the manager's real name. You only do this once per person.")


if __name__ == "__main__":
    if "--offline" not in sys.argv:
        fetch_all()
    build_db()
