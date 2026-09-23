"""Bronze -> silver: normalise genuinely comparable concepts across providers;
keep provider-specific event/metric schemas separate rather than forcing them
into one shared shape (per instruction: do not combine similarly-named
metrics across providers unless their definitions are compatible).

Every silver table carries a `source` column and every row's provider-native
ID, so nothing here silently merges cross-provider identity. No player/team
identity resolution across providers is attempted (would need Reep or an
equivalent reviewable identity table) - each source's players/teams stay
source-scoped.
"""
import json
import duckdb
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRONZE = ROOT / "bronze"
SILVER = ROOT / "silver"

con = duckdb.connect()

# ---------------------------------------------------------------------------
# competitions (genuinely comparable envelope: id, name, country, gender)
# ---------------------------------------------------------------------------
sb_comps = json.load(open(BRONZE / "statsbomb/2026-09-23/competitions.json"))
sb_comp_rows = [{
    "source": "statsbomb",
    "competition_id": str(c["competition_id"]),
    "season_id": str(c["season_id"]),
    "competition_name": c["competition_name"],
    "season_name": c["season_name"],
    "country": c["country_name"],
    "gender": c["competition_gender"],
    "has_360": bool(c.get("match_available_360")),
} for c in sb_comps]

sk_matches = json.load(open(BRONZE / "skillcorner/2026-09-23/matches.json"))
sk_comp_rows = [{
    "source": "skillcorner",
    "competition_id": str(sk_matches[0]["competition_id"]),
    "season_id": str(sk_matches[0]["season_id"]),
    "competition_name": "A-League",
    "season_name": "2024/2025",
    "country": "AUS",
    "gender": "male",
    "has_360": False,
}]

wy_comp_rows = [{
    "source": "wyscout",
    "competition_id": "wyscout-england-2017-18",
    "season_id": "2017-18",
    "competition_name": "Premier League",
    "season_name": "2017/18",
    "country": "England",
    "gender": "male",
    "has_360": False,
}]

competitions = pd.DataFrame(sb_comp_rows + sk_comp_rows + wy_comp_rows)
con.register("competitions_df", competitions)
con.execute(f"COPY competitions_df TO '{SILVER}/competitions/competitions.parquet' (FORMAT PARQUET)")
print(f"competitions: {len(competitions)} rows")

# ---------------------------------------------------------------------------
# matches (genuinely comparable envelope)
# ---------------------------------------------------------------------------
sb_matches_wc18 = json.load(open(BRONZE / "statsbomb/2026-09-23/matches_43_3_wc2018.json"))
sb_matches_wc22 = json.load(open(BRONZE / "statsbomb/2026-09-23/matches_43_106_wc2022.json"))
match_rows = []
for m in sb_matches_wc18 + sb_matches_wc22:
    if m["match_id"] not in (8658, 3869685):
        continue  # only the 2 matches we actually pulled full event data for
    match_rows.append({
        "source": "statsbomb", "match_id": str(m["match_id"]),
        "competition_id": str(m["competition"]["competition_id"]),
        "season_id": str(m["season"]["season_id"]),
        "match_date": m["match_date"],
        "home_team": m["home_team"]["home_team_name"],
        "away_team": m["away_team"]["away_team_name"],
        "home_score": m["home_score"], "away_score": m["away_score"],
        "competition_stage": m.get("competition_stage", {}).get("name"),
    })

for m in sk_matches:
    match_rows.append({
        "source": "skillcorner", "match_id": str(m["id"]),
        "competition_id": str(m["competition_id"]), "season_id": str(m["season_id"]),
        "match_date": m["date_time"],
        "home_team": m["home_team"]["short_name"], "away_team": m["away_team"]["short_name"],
        "home_score": None, "away_score": None,  # scores live in per-match match.json, not the manifest
        "competition_stage": None,
    })

wy_match = json.load(open(BRONZE / "wyscout/2026-09-23/match_2499743_liverpool_arsenal.json"))
wy_teams = wy_match["teams"]
team_names = {tid: t["team"]["name"] for tid, t in wy_teams.items()}
match_rows.append({
    "source": "wyscout", "match_id": "2499743",
    "competition_id": "wyscout-england-2017-18", "season_id": "2017-18",
    "match_date": "2017-08-27", "home_team": "Liverpool", "away_team": "Arsenal",
    "home_score": 4, "away_score": 0, "competition_stage": None,
})

matches = pd.DataFrame(match_rows)
con.register("matches_df", matches)
con.execute(f"COPY matches_df TO '{SILVER}/matches/matches.parquet' (FORMAT PARQUET)")
print(f"matches: {len(matches)} rows")

print("silver competitions + matches done")
