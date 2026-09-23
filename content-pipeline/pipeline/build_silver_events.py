"""Provider-specific event/metric tables. Kept separate per provider (own
schema, own coordinate convention, own vocabulary) rather than unioned into
one 'events' table - StatsBomb/SkillCorner/Wyscout event definitions are not
directly comparable field-for-field.
"""
import json
import duckdb
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRONZE = ROOT / "bronze"
SILVER = ROOT / "silver"
con = duckdb.connect()


def flatten_sb_event(e, match_id):
    loc = e.get("location", [None, None])
    row = {
        "match_id": match_id, "event_id": e["id"], "index": e.get("index"),
        "period": e.get("period"), "minute": e.get("minute"), "second": e.get("second"),
        "team_id": e.get("team", {}).get("id"), "team_name": e.get("team", {}).get("name"),
        "player_id": e.get("player", {}).get("id"), "player_name": e.get("player", {}).get("name"),
        "event_type": e.get("type", {}).get("name"),
        "x": loc[0] if loc else None, "y": loc[1] if loc else None,
        "possession": e.get("possession"),
    }
    if e.get("type", {}).get("name") == "Pass":
        p = e["pass"]
        end = p.get("end_location", [None, None])
        row.update({
            "pass_end_x": end[0], "pass_end_y": end[1],
            "pass_outcome": p.get("outcome", {}).get("name", "Complete"),
            "pass_height": p.get("height", {}).get("name"),
        })
    if e.get("type", {}).get("name") == "Shot":
        s = e["shot"]
        row.update({
            "shot_statsbomb_xg": s.get("statsbomb_xg"),
            "shot_outcome": s.get("outcome", {}).get("name"),
            "shot_has_freeze_frame": "freeze_frame" in s,
        })
    return row


# --- StatsBomb events: the 2 matches we pulled ---
sb_rows = []
for match_id, fname in [(8658, "events_8658_wc2018final.json"), (3869685, "events_3869685_wc2022final.json")]:
    events = json.load(open(BRONZE / "statsbomb/2026-09-23" / fname))
    for e in events:
        sb_rows.append(flatten_sb_event(e, match_id))
sb_events = pd.DataFrame(sb_rows)
con.register("sb_events_df", sb_events)
con.execute(f"COPY sb_events_df TO '{SILVER}/statsbomb_events/events.parquet' (FORMAT PARQUET)")
print(f"statsbomb_events: {len(sb_events)} rows")

# --- StatsBomb 360 freeze frames (event-anchored spatial_context, WC2022 final only) ---
# NOTE ON A RECONCILIATION FINDING: StatsBomb carries freeze-frame positions
# in TWO places for the same shot event - (a) embedded in the event's own
# shot.freeze_frame (named players, used here), and (b) the separate
# data/three-sixty/{match}.json file keyed by event_uuid (anonymised,
# actor/keeper flags). For the one event checked by hand (Mbappe's 80th-min
# shot, WC2022 Final), both describe the same 8 real Argentina outfield+GK
# players but with slightly different coordinates for each (nearest-opponent
# distance: 4.05m from the embedded field vs 3.41m from the standalone file -
# a real, disclosed discrepancy, not a bug being hidden). This pipeline uses
# the EMBEDDED shot.freeze_frame as the source of record because it carries
# player identity (needed to say who the nearest opponent was), and notes the
# standalone file's value in the claim-audit file rather than silently
# picking one number. Neither field is proven to capture every player on the
# pitch, so no claim built from either should say "nearest defender" as an
# absolute - say "nearest CAPTURED opponent in the freeze-frame".
events_raw = json.load(open(BRONZE / "statsbomb/2026-09-23/events_3869685_wc2022final.json"))
ff_rows = []
for e in events_raw:
    if e.get("type", {}).get("name") == "Shot" and "freeze_frame" in e.get("shot", {}):
        for p in e["shot"]["freeze_frame"]:
            ff_rows.append({
                "match_id": 3869685, "event_uuid": e["id"],
                "x": p["location"][0], "y": p["location"][1],
                "teammate": p["teammate"], "player_name": p["player"]["name"],
                "player_position": p["position"]["name"],
            })
ff = pd.DataFrame(ff_rows)
con.register("ff_df", ff)
con.execute(f"COPY ff_df TO '{SILVER}/statsbomb_360_freeze_frames/frames.parquet' (FORMAT PARQUET)")
print(f"statsbomb_360_freeze_frames: {len(ff)} rows, from embedded shot.freeze_frame (event-anchored, NOT continuous tracking)")

# --- SkillCorner dynamic events + phases of play (match 1874553) ---
de = pd.read_csv(BRONZE / "skillcorner/2026-09-23/match_1874553/1874553_dynamic_events.csv")
con.register("de_df", de)
con.execute(f"COPY de_df TO '{SILVER}/skillcorner_dynamic_events/events.parquet' (FORMAT PARQUET)")
print(f"skillcorner_dynamic_events: {len(de)} rows, {len(de.columns)} cols")

pp = pd.read_csv(BRONZE / "skillcorner/2026-09-23/match_1874553/1874553_phases_of_play.csv")
con.register("pp_df", pp)
con.execute(f"COPY pp_df TO '{SILVER}/skillcorner_phases_of_play/phases.parquet' (FORMAT PARQUET)")
print(f"skillcorner_phases_of_play: {len(pp)} rows")

# --- SkillCorner season aggregates (full A-League 2024/25 season) ---
for name, sub in [("physical", "skillcorner_season_physical"),
                   ("passing", "skillcorner_season_passing"),
                   ("obr", "skillcorner_season_offballrun")]:
    df = pd.read_csv(BRONZE / f"skillcorner/2026-09-23/aggregates/aus1league_{name}aggregates_20242025.csv")
    con.register(f"{name}_df", df)
    con.execute(f"COPY {name}_df TO '{SILVER}/{sub}/{name}.parquet' (FORMAT PARQUET)")
    print(f"{sub}: {len(df)} rows, {len(df.columns)} cols")

# --- Wyscout events (Liverpool 4-0 Arsenal) ---
wy = json.load(open(BRONZE / "wyscout/2026-09-23/match_2499743_liverpool_arsenal.json"))
wy_rows = []
for e in wy["events"]:
    pos = e.get("positions", [{}])
    start = pos[0] if len(pos) > 0 else {}
    end = pos[1] if len(pos) > 1 else {}
    wy_rows.append({
        "match_id": e["matchId"], "event_id": e["id"], "team_id": e["teamId"],
        "player_id": e["playerId"], "event_name": e["eventName"], "sub_event_name": e.get("subEventName"),
        "match_period": e["matchPeriod"], "event_sec": e["eventSec"],
        "x_start": start.get("x"), "y_start": start.get("y"),
        "x_end": end.get("x"), "y_end": end.get("y"),
        "tag_ids": ",".join(str(t["id"]) for t in e.get("tags", [])),
    })
wy_events = pd.DataFrame(wy_rows)
con.register("wy_events_df", wy_events)
con.execute(f"COPY wy_events_df TO '{SILVER}/wyscout_events/events.parquet' (FORMAT PARQUET)")
print(f"wyscout_events: {len(wy_events)} rows")

print("\nall silver event/metric tables built")
