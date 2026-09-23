"""Entity inventory: players, teams, competitions, one row per provider per
entity.

NAMING NOTE: this was called an "identity-resolution table" in an earlier
pass. That name overstates what this is - resolution implies entities have
actually been matched across providers, and none have. This is an
**inventory** of each provider's own entities, nothing more, until a real
matching pass (manual or reviewed) populates alias_group_id. Renamed to
build_entity_inventory.py / entity_inventory_* accordingly; treat any
lingering reference to "identity_teams" etc. elsewhere as stale.

STRICT RULE: this script NEVER merges an entity across providers
automatically, no matter how confident a name match looks. Every row here is
one provider's own record of one entity, tagged with that provider's own ID
and name, verbatim. Cross-provider linking is a SEPARATE, manual step: the
`alias_group_id` column exists on every table and is left NULL by this
script for every row - a human (or a future, explicitly-reviewed matching
pass) fills it in, and `confidence`/`manual_review_needed` describe that
review state, not an automated guess. Until that pass exists, do not query
these tables as if `alias_group_id` means anything - it doesn't yet.

Re-runnable: safe to run again as more bronze data arrives (e.g. once the
StatsBomb/Wyscout bulk downloads finish) - it reads whatever bronze files
exist at run time and simply produces a larger table.
"""
import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from acquisition.framework import DATA

BRONZE = DATA / "bronze"
SILVER = DATA / "silver"


def build_teams_and_players_from_statsbomb():
    teams, players = {}, {}
    lineup_files = list((BRONZE / "statsbomb").glob("*/lineups/*.json"))
    for f in lineup_files:
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        for team in data:
            tid = team.get("team_id")
            if tid is not None:
                teams[("statsbomb", tid)] = {
                    "provider": "statsbomb", "provider_id": str(tid),
                    "provider_name": team.get("team_name"), "country": None,
                }
            for p in team.get("lineup", []):
                pid = p.get("player_id")
                if pid is not None:
                    players[("statsbomb", pid)] = {
                        "provider": "statsbomb", "provider_id": str(pid),
                        "provider_name": p.get("player_name"),
                        "country": (p.get("country") or {}).get("name"),
                        "team_provider_id": str(tid) if tid is not None else None,
                    }
    return teams, players


def build_teams_and_players_from_wyscout():
    teams, players = {}, {}
    match_files = list((BRONZE / "wyscout").glob("*/matches/*.json"))
    for f in match_files:
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        team_block = data.get("teams", {})
        items = team_block.items() if isinstance(team_block, dict) else enumerate(team_block)
        for key, t in items:
            info = t.get("team", t) if isinstance(t, dict) else {}
            tid = info.get("wyId") or key
            if tid is not None:
                teams[("wyscout", tid)] = {
                    "provider": "wyscout", "provider_id": str(tid),
                    "provider_name": info.get("name") or info.get("officialName"),
                    "country": (info.get("area") or {}).get("name"),
                }
        player_block = data.get("players", {})
        p_items = player_block.items() if isinstance(player_block, dict) else []
        for key, p in p_items:
            info = p.get("player", p) if isinstance(p, dict) else {}
            pid = info.get("wyId") or key
            if pid is not None:
                players[("wyscout", pid)] = {
                    "provider": "wyscout", "provider_id": str(pid),
                    "provider_name": (info.get("shortName") or
                                      f"{info.get('firstName','')} {info.get('lastName','')}".strip()),
                    "country": (info.get("passportArea") or {}).get("name"),
                    "team_provider_id": None,
                }
    return teams, players


def build_teams_and_players_from_skillcorner():
    teams, players = {}, {}
    matches_files = list((BRONZE / "skillcorner").glob("*/matches.json"))
    for f in matches_files:
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        for m in data:
            for side in ("home_team", "away_team"):
                t = m.get(side, {})
                tid = t.get("id")
                if tid is not None:
                    teams[("skillcorner", tid)] = {
                        "provider": "skillcorner", "provider_id": str(tid),
                        "provider_name": t.get("short_name"), "country": None,
                    }
    agg_files = list((BRONZE / "skillcorner").glob("*/aggregates/*physicalaggregates*.csv"))
    for f in agg_files:
        try:
            df = pd.read_csv(f)
        except Exception:
            continue
        for _, row in df.iterrows():
            pid = row.get("player_id")
            if pd.notna(pid):
                players[("skillcorner", int(pid))] = {
                    "provider": "skillcorner", "provider_id": str(int(pid)),
                    "provider_name": row.get("player_name"), "country": None,
                    "team_provider_id": str(int(row["team_id"])) if pd.notna(row.get("team_id")) else None,
                }
    return teams, players


def build_competitions():
    rows = []
    comp_files = list((BRONZE / "statsbomb").glob("*/competitions.json"))
    for f in comp_files:
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        for c in data:
            rows.append({
                "provider": "statsbomb", "provider_id": f"{c['competition_id']}_{c['season_id']}",
                "provider_name": f"{c['competition_name']} {c['season_name']}",
                "country": c.get("country_name"), "gender": c.get("competition_gender"),
                "alias_group_id": None, "confidence": "unresolved", "manual_review_needed": True,
            })
    # Wyscout and SkillCorner competitions were already catalogued in
    # content-pipeline's earlier silver/competitions table (3 rows) - merged
    # in by the caller, not re-derived here to avoid duplicating that logic.
    return rows


def to_rows(entity_dict):
    rows = []
    for (provider, _key), rec in entity_dict.items():
        rec = dict(rec)
        rec["alias_group_id"] = None
        rec["confidence"] = "unresolved"
        rec["manual_review_needed"] = True
        rec["notes"] = ""
        rows.append(rec)
    return rows


def main():
    SILVER.mkdir(parents=True, exist_ok=True)
    all_teams, all_players = {}, {}
    for builder in [build_teams_and_players_from_statsbomb, build_teams_and_players_from_wyscout,
                     build_teams_and_players_from_skillcorner]:
        t, p = builder()
        all_teams.update(t)
        all_players.update(p)

    teams_rows = to_rows(all_teams)
    players_rows = to_rows(all_players)
    comp_rows = build_competitions()

    con = duckdb.connect()
    for name, rows in [("entity_inventory_teams", teams_rows), ("entity_inventory_players", players_rows),
                        ("entity_inventory_competitions", comp_rows)]:
        if not rows:
            print(f"{name}: 0 rows (no source data yet)")
            continue
        df = pd.DataFrame(rows)
        con.register("df", df)
        out_dir = SILVER / name
        out_dir.mkdir(parents=True, exist_ok=True)
        con.execute(f"COPY df TO '{out_dir}/{name}.parquet' (FORMAT PARQUET)")
        df.to_csv(out_dir / f"{name}.csv", index=False)
        print(f"{name}: {len(df)} rows ({df['provider'].nunique()} providers)")

    print("\nEvery row's alias_group_id is NULL and manual_review_needed=True by design - "
          "no cross-provider identity was merged automatically. See docs/ for the manual review process.")


if __name__ == "__main__":
    main()
