"""StatsBomb Open Data adapter. Source: github.com/statsbomb/open-data
(branch master). Licence: StatsBomb User Agreement - free, attribution
required ("StatsBomb" + logo), non-commercial/research use.

Deliberately does NOT `git clone` the repo - that stalled indefinitely in
this environment for this specific large repo (see docs/CAPABILITY_MATRIX.md
"Session note"). Every file is fetched individually via
raw.githubusercontent.com, which is what actually works here.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from acquisition.framework import Acquirer

BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master"
LICENCE = "StatsBomb User Agreement - free, attribution required (credit 'StatsBomb' + logo), non-commercial/research use"


def fetch_competitions(acq: Acquirer) -> list:
    r = acq.fetch(
        source="statsbomb", resource_type="competitions", resource_key="competitions",
        url=f"{BASE}/data/competitions.json", dest_relpath="competitions.json",
        licence_tag=LICENCE, expect_json=True,
    )
    from acquisition.framework import DATA
    path = DATA / "bronze" / "statsbomb" / acq.snapshot / "competitions.json"
    return json.load(open(path))


def fetch_all_match_lists(acq: Acquirer, competitions: list) -> dict:
    """Returns {(competition_id, season_id): [match dicts]}"""
    from acquisition.framework import DATA
    out = {}
    for c in competitions:
        cid, sid = c["competition_id"], c["season_id"]
        key = f"{cid}_{sid}"
        r = acq.fetch(
            source="statsbomb", resource_type="matches_list", resource_key=key,
            url=f"{BASE}/data/matches/{cid}/{sid}.json",
            dest_relpath=f"matches/{cid}/{sid}.json",
            licence_tag=LICENCE, expect_json=True,
        )
        if r.status in ("done", "skipped_already_done"):
            path = DATA / "bronze" / "statsbomb" / acq.snapshot / f"matches/{cid}/{sid}.json"
            try:
                out[(cid, sid)] = json.load(open(path))
            except Exception:
                out[(cid, sid)] = []
        else:
            out[(cid, sid)] = []
    return out


def plan(acq: Acquirer):
    """Inventory-only pass: competitions + every match list. Cheap (~80 requests).
    Returns (competitions, match_lists, total_matches, total_360_matches)."""
    competitions = fetch_competitions(acq)
    match_lists = fetch_all_match_lists(acq, competitions)
    total_matches = sum(len(v) for v in match_lists.values())
    total_360 = sum(1 for v in match_lists.values() for m in v if m.get("match_status_360") == "available" or m.get("match_available_360"))
    # 360 availability is actually a per-competition-season flag in competitions.json,
    # not reliably per-match in the matches list - recompute from competitions instead.
    comps_with_360 = {(c["competition_id"], c["season_id"]) for c in competitions if c.get("match_available_360")}
    total_360 = sum(len(match_lists.get(k, [])) for k in comps_with_360)
    return competitions, match_lists, total_matches, total_360


def run(acq: Acquirer, match_lists: dict, competitions: list, limit: int = None):
    """Full download pass: events + lineups + 360 (where the competition-season
    has 360) for every match. `limit` caps the number of matches processed,
    for testing - omit for a full run."""
    comps_with_360 = {(c["competition_id"], c["season_id"]) for c in competitions if c.get("match_available_360")}
    n = 0
    for (cid, sid), matches in match_lists.items():
        has_360 = (cid, sid) in comps_with_360
        for m in matches:
            if limit is not None and n >= limit:
                return
            mid = m["match_id"]
            acq.fetch(
                source="statsbomb", resource_type="events", resource_key=str(mid),
                url=f"{BASE}/data/events/{mid}.json", dest_relpath=f"events/{mid}.json",
                licence_tag=LICENCE, expect_json=True,
            )
            acq.fetch(
                source="statsbomb", resource_type="lineups", resource_key=str(mid),
                url=f"{BASE}/data/lineups/{mid}.json", dest_relpath=f"lineups/{mid}.json",
                licence_tag=LICENCE, expect_json=True,
            )
            if has_360:
                acq.fetch(
                    source="statsbomb", resource_type="three_sixty", resource_key=str(mid),
                    url=f"{BASE}/data/three-sixty/{mid}.json", dest_relpath=f"three-sixty/{mid}.json",
                    licence_tag=LICENCE, expect_json=True,
                )
            n += 1


if __name__ == "__main__":
    acq = Acquirer()
    competitions, match_lists, total_matches, total_360 = plan(acq)
    print(f"StatsBomb inventory: {len(competitions)} competition-seasons, "
          f"{total_matches} total matches, {total_360} with 360 data")
    print(f"Estimated file count: {total_matches} events + {total_matches} lineups + {total_360} three-sixty "
          f"= {total_matches*2 + total_360} files")
    acq.close()
