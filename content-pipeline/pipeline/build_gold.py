"""Silver -> gold: reproducible, post-ready metric values, computed via
DuckDB SQL against the silver Parquet tables (not re-derived by hand) so the
numbers behind post_candidates.csv are independently re-runnable.
"""
import duckdb
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SILVER = ROOT / "silver"
GOLD = ROOT / "gold"
con = duckdb.connect()

results = {}

# 1. Field tilt, WC2018 Final (StatsBomb) -----------------------------------
q = f"""
WITH completed_passes AS (
    SELECT * FROM read_parquet('{SILVER}/statsbomb_events/events.parquet')
    WHERE match_id = 8658 AND event_type = 'Pass' AND pass_outcome = 'Complete'
),
final_third AS (SELECT * FROM completed_passes WHERE x > 80)
SELECT team_name, count(*) AS final_third_passes,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS field_tilt_pct
FROM final_third GROUP BY team_name ORDER BY field_tilt_pct DESC
"""
df = con.execute(q).df()
results["field_tilt_wc2018_final"] = df
print("=== 1. Field tilt WC2018 Final ===\n", df, "\n")

# 2. Mbappe 360 nearest-CAPTURED-opponent, WC2022 Final ---------------------
q = f"""
WITH shot AS (
    SELECT event_id, x AS shot_x, y AS shot_y
    FROM read_parquet('{SILVER}/statsbomb_events/events.parquet')
    WHERE match_id = 3869685 AND event_type = 'Shot' AND minute = 80 AND second = 59
),
frame AS (
    SELECT f.* FROM read_parquet('{SILVER}/statsbomb_360_freeze_frames/frames.parquet') f, shot
    WHERE f.event_uuid = shot.event_id
)
SELECT frame.player_name, frame.player_position,
       round(sqrt(power(frame.x - shot.shot_x,2) + power(frame.y - shot.shot_y,2)), 2) AS dist_m
FROM frame, shot WHERE frame.teammate = false ORDER BY dist_m
"""
df = con.execute(q).df()
results["mbappe_360_wc2022_final"] = df
print("=== 2. Mbappe 360 nearest captured opponents, WC2022 Final (from embedded shot.freeze_frame) ===\n", df, "\n")
print("NOTE:", len(df), "captured opposition players (8 outfield+GK) out of 11 Argentina players on the pitch",
      "- PARTIAL freeze frame, so claims must say 'nearest CAPTURED opponent', never 'nearest defender' as",
      "if completeness were proven. A second, separate StatsBomb 360 field (the standalone three-sixty file)",
      "gives a slightly different value (3.41m vs this table's 4.05m) for the same event - both are real",
      "StatsBomb fields: see docs/CAPABILITY_MATRIX.md and the claim-audit file for the reconciliation note.\n")

# 3. SkillCorner season physical comparison ----------------------------------
q = f"""
SELECT player_name, team_name, position_group, count_match,
       round(minutes_full_all * count_match, 1) AS total_minutes_est,
       round(sprint_distance_full_all / minutes_full_all * 90, 1) AS sprint_distance_p90,
       psv99
FROM read_parquet('{SILVER}/skillcorner_season_physical/physical.parquet')
WHERE player_name IN ('Dylan Pierias', 'Brandon Borrello')
"""
df = con.execute(q).df()
results["skillcorner_season_comparison"] = df
print("=== 3. SkillCorner season physical comparison ===\n", df, "\n")

# 4. SkillCorner EPV story ----------------------------------------------------
q = f"""
SELECT event_id, minute_start, second_start, team_shortname, player_name,
       pass_epv_delta_for, pass_epv_total, lead_to_shot, lead_to_goal, pass_outcome
FROM read_parquet('{SILVER}/skillcorner_dynamic_events/events.parquet')
WHERE pass_epv_delta_for IS NOT NULL
ORDER BY pass_epv_delta_for DESC LIMIT 3
"""
df = con.execute(q).df()
results["skillcorner_epv_top3"] = df
print("=== 4. SkillCorner EPV top events ===\n", df, "\n")

# 5. SkillCorner pressure/reception-difficulty story --------------------------
q = f"""
SELECT event_id, minute_start, second_start, team_shortname, player_name,
       overall_pressure_start, reception_difficulty_start, space_constraint_start, pass_outcome
FROM read_parquet('{SILVER}/skillcorner_dynamic_events/events.parquet')
WHERE pass_outcome = 'successful'
  AND overall_pressure_start = 'very_high_pressure'
  AND reception_difficulty_start = 'hard'
  AND space_constraint_start = 'very_hard'
"""
df = con.execute(q).df()
results["skillcorner_pressure_story"] = df
print("=== 5. SkillCorner pressure story ===\n", df, "\n")

# 6. SkillCorner opponents-bypassed story -------------------------------------
q = f"""
SELECT event_id, minute_start, second_start, team_shortname, player_name,
       n_opponents_bypassed, first_line_break, last_line_break, pass_outcome
FROM read_parquet('{SILVER}/skillcorner_dynamic_events/events.parquet')
WHERE pass_outcome = 'successful' AND n_opponents_bypassed IS NOT NULL
ORDER BY n_opponents_bypassed DESC LIMIT 3
"""
df = con.execute(q).df()
results["skillcorner_bypass_top3"] = df
print("=== 6. SkillCorner bypass top events ===\n", df, "\n")

# 7. SkillCorner team-shape story ---------------------------------------------
q = f"""
SELECT team_in_possession_shortname, period,
       round(avg((team_in_possession_width_start + team_in_possession_width_end)/2.0), 2) AS avg_width,
       count(*) AS n_phases
FROM read_parquet('{SILVER}/skillcorner_phases_of_play/phases.parquet')
GROUP BY 1, 2 ORDER BY 1, 2
"""
df = con.execute(q).df()
results["skillcorner_team_shape"] = df
print("=== 7. SkillCorner team shape by half ===\n", df, "\n")

# 8. Wyscout: Liverpool 4-0 Arsenal shot map sanity (validates 3rd source is queryable) --
q = f"""
SELECT team_id, count(*) AS shots
FROM read_parquet('{SILVER}/wyscout_events/events.parquet')
WHERE event_name = 'Shot' GROUP BY team_id
"""
df = con.execute(q).df()
results["wyscout_shot_counts"] = df
print("=== 8. Wyscout shot counts (validation query) ===\n", df, "\n")

# Save every gold table
GOLD.mkdir(exist_ok=True)
for name, df in results.items():
    df.to_parquet(GOLD / f"{name}.parquet", index=False)
    df.to_csv(GOLD / f"{name}.csv", index=False)
print(f"\nWrote {len(results)} gold tables to {GOLD}/")
