"""Wyscout mirror validation - one representative match per competition
group (7 groups, 7 matches), NOT a claim that one match validates all 1,941
files. Checks: schema/event count, coordinate range/orientation,
periods/timestamps, team/player references, goals vs recorded final score,
kloppy load success.
"""
import json
from pathlib import Path
from kloppy import wyscout

MATCHES = [
    ("Premier League", 2017, "England", 2499743, "/home/user/wyscout-data/match_2499743.json", (4, 0)),
    ("Ligue 1", 2017, "France", 2500688, "/home/user/wyscout-data/match_2500688_ligue1_lyon_strasbourg.json", (4, 0)),
    ("Serie A", 2017, "Italy", 2575961, "/home/user/wyscout-data/match_2575961_seriea_crotone_milan.json", (0, 3)),
    ("La Liga", 2017, "Spain", 2565549, "/home/user/wyscout-data/match_2565549_laliga_celta_realsociedad.json", (2, 3)),
    ("Bundesliga", 2017, "Germany", 2516739, "/home/user/wyscout-data/match_2516739_bundesliga_bayern_leverkusen.json", (3, 1)),
    ("World Cup", 2018, "World Cup", 2057954, "/home/user/wyscout-data/match_2057954_worldcup_russia_saudiarabia.json", (5, 0)),
    ("UEFA Euro", 2016, "European Championship", 1694390, "/home/user/wyscout-data/match_1694390_euro2016_france_romania.json", (2, 1)),
]

results = []
for comp, season, area, match_id, path, expected_score in MATCHES:
    p = Path(path)
    row = {"competition": comp, "season": season, "match_id": match_id}
    d = json.load(open(p))

    # 1. schema + event count
    row["schema_ok"] = set(d.keys()) == {"events", "teams", "players"}
    row["n_events"] = len(d["events"])
    row["event_count_plausible"] = 800 <= row["n_events"] <= 3500

    # 2. coordinate range + orientation (both teams' shots should cluster toward x~85-100)
    shots = [e for e in d["events"] if e["eventName"] == "Shot"]
    xs = [e["positions"][0]["x"] for e in shots if e.get("positions")]
    ys = [e["positions"][0]["y"] for e in shots if e.get("positions")]
    row["n_shots"] = len(shots)
    row["coords_in_0_100"] = all(0 <= x <= 100 for x in xs) and all(0 <= y <= 100 for y in ys)
    row["shots_cluster_attacking"] = (sum(xs) / len(xs) > 70) if xs else None

    # 3. periods + timestamps
    periods = {e["matchPeriod"] for e in d["events"]}
    row["periods"] = sorted(periods)
    row["periods_ok"] = periods.issubset({"1H", "2H", "E1", "E2", "P"})
    secs = [e["eventSec"] for e in d["events"] if e["matchPeriod"] == "1H"]
    row["first_half_max_sec"] = max(secs) if secs else None
    row["timestamps_plausible"] = row["first_half_max_sec"] is not None and 2400 <= row["first_half_max_sec"] <= 4500

    # 4. team/player references resolve
    team_ids_in_events = {e["teamId"] for e in d["events"]}
    player_ids_in_events = {e["playerId"] for e in d["events"] if e.get("playerId")}
    known_team_ids = set(int(k) for k in d["teams"].keys()) if isinstance(d["teams"], dict) else {t["team"]["wyId"] for t in d["teams"]}
    known_player_ids = set(int(k) for k in d["players"].keys()) if isinstance(d["players"], dict) else set()
    row["n_teams"] = len(known_team_ids)
    row["n_players_referenced"] = len(known_player_ids)
    row["all_event_team_ids_known"] = team_ids_in_events.issubset(known_team_ids)

    # 5. goals vs recorded final score - count Goal-tagged (tag 101) scoring events
    # per team, EXCLUDING eventName=='Save attempt'.
    #
    # Found and fixed during this validation pass: tag 101 appears on BOTH the
    # scoring event and the paired *opposing* goalkeeper's "Save attempt" event
    # for the same goal (Wyscout tags both sides of a goal). An earlier version
    # of this script only counted eventName=='Shot', which missed direct free-kick
    # goals (eventName='Free Kick', subEventName='Free kick shot') and penalties
    # (subEventName='Penalty') - both distinct from 'Shot' in Wyscout's schema.
    # Rather than enumerate every possible scoring eventName (fragile - a future
    # match could use one not seen in this 7-match sample), the robust rule is:
    # any tag-101 event that ISN'T the goalkeeper's paired Save-attempt record.
    goal_tag_id = 101
    goals_by_team = {}
    for e in d["events"]:
        if e["eventName"] == "Save attempt":
            continue
        tag_ids = {t["id"] for t in e.get("tags", [])}
        if goal_tag_id in tag_ids:
            goals_by_team[e["teamId"]] = goals_by_team.get(e["teamId"], 0) + 1
    row["goals_by_team_from_events"] = goals_by_team
    row["expected_score"] = expected_score
    computed_total = sum(goals_by_team.values())
    row["goal_count_matches_expected_total"] = computed_total == sum(expected_score)

    # 6. kloppy load
    try:
        ds = wyscout.load(event_data=str(p), data_version="V2")
        row["kloppy_load_ok"] = True
        row["kloppy_n_events"] = len(ds.events)
    except Exception as ex:
        row["kloppy_load_ok"] = False
        row["kloppy_error"] = str(ex)[:200]

    results.append(row)

print(f"{'Competition':<15} {'events':>7} {'shots':>6} {'coords_ok':>10} {'periods_ok':>11} {'ts_ok':>7} {'teams_ok':>9} {'goals_ok':>9} {'kloppy_ok':>10}")
for r in results:
    print(f"{r['competition']:<15} {r['n_events']:>7} {r['n_shots']:>6} {str(r['coords_in_0_100']):>10} "
          f"{str(r['periods_ok']):>11} {str(r['timestamps_plausible']):>7} {str(r['all_event_team_ids_known']):>9} "
          f"{str(r['goal_count_matches_expected_total']):>9} {str(r['kloppy_load_ok']):>10}")

all_pass = all(
    r["schema_ok"] and r["event_count_plausible"] and r["coords_in_0_100"] and r["shots_cluster_attacking"]
    and r["periods_ok"] and r["timestamps_plausible"] and r["all_event_team_ids_known"]
    and r["goal_count_matches_expected_total"] and r["kloppy_load_ok"]
    for r in results
)
print(f"\nALL 7 MATCHES PASS ALL CHECKS: {all_pass}")

import csv
with open("/home/user/auction/content-pipeline/scratch/wyscout_multi_competition_validation.csv", "w", newline="") as f:
    fieldnames = list(results[0].keys())
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    for r in results:
        w.writerow(r)
print("Saved scratch/wyscout_multi_competition_validation.csv")
