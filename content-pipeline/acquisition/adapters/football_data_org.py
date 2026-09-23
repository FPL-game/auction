"""football-data.org adapter. NOT RUNNABLE in this sandbox -
api.football-data.org is blocked by this session's network egress policy.
Also requires a free API key this project does not have and cannot obtain
on the user's behalf (self-serve signup at football-data.org/client/register).

Licence: free tier terms per football-data.org's own ToS - rate-limited
(10 calls/minute on the free tier, per their docs), attribution requested.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from acquisition.framework import Acquirer

BASE = "https://api.football-data.org/v4"
LICENCE = "football-data.org free tier - rate-limited (10 req/min), attribution requested per their ToS"

# The free tier's own documented competition codes for major leagues.
COMPETITIONS = ["PL", "PD", "SA", "BL1", "FL1", "CL", "WC", "EC"]


def run(acq: Acquirer, api_key: str = None):
    api_key = api_key or os.environ.get("FOOTBALL_DATA_ORG_API_KEY")
    if not api_key:
        raise RuntimeError(
            "FOOTBALL_DATA_ORG_API_KEY not set. Get a free key at "
            "https://www.football-data.org/client/register and export it before running this adapter."
        )
    acq.session.headers["X-Auth-Token"] = api_key
    for comp in COMPETITIONS:
        acq.fetch(
            source="football_data_org", resource_type="competition", resource_key=comp,
            url=f"{BASE}/competitions/{comp}", dest_relpath=f"competitions/{comp}.json",
            licence_tag=LICENCE, rate_limit_sec=6.5,  # 10 req/min free-tier limit -> >=6s between calls
            expect_json=True,
        )
        acq.fetch(
            source="football_data_org", resource_type="competition_matches", resource_key=comp,
            url=f"{BASE}/competitions/{comp}/matches", dest_relpath=f"matches/{comp}.json",
            licence_tag=LICENCE, rate_limit_sec=6.5, expect_json=True,
        )


if __name__ == "__main__":
    print("This adapter is NOT run automatically in this sandbox - see "
          "acquisition/run_blocked_sources.py and docs/BLOCKED_SOURCE_COLLECTION.md")
