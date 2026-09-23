"""football-data.co.uk adapter. NOT RUNNABLE in this sandbox -
www.football-data.co.uk is blocked by this session's network egress policy
(confirmed via direct connection attempt, see docs/CAPABILITY_MATRIX.md).
Built for a machine outside the sandbox - see acquisition/run_blocked_sources.py.

Licence: free for personal/non-commercial use (per the site); commercial use
requires asking the site owner. This project's use (personal study) is
within the stated free-use terms.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from acquisition.framework import Acquirer

BASE = "https://www.football-data.co.uk/mmz4281"
LICENCE = "football-data.co.uk - free for personal/non-commercial use; ask the site owner for commercial use"

# League codes -> plain names, per football-data.co.uk's own scheme.
LEAGUES = {
    "E0": "Premier League", "E1": "Championship", "E2": "League One", "E3": "League Two",
    "SP1": "La Liga", "SP2": "La Liga 2",
    "I1": "Serie A", "I2": "Serie B",
    "D1": "Bundesliga", "D2": "Bundesliga 2",
    "F1": "Ligue 1", "F2": "Ligue 2",
    "N1": "Eredivisie", "B1": "Belgian Pro League", "P1": "Primeira Liga",
    "SC0": "Scottish Premiership",
}


def season_codes(start_year: int = 1993, end_year: int = 2026) -> list:
    """football-data.co.uk season format: '9394' for 1993/94, '2425' for 2024/25."""
    out = []
    for y in range(start_year, end_year):
        out.append(f"{str(y)[-2:]}{str(y + 1)[-2:]}")
    return out


def run(acq: Acquirer, leagues: dict = None, seasons: list = None, rate_limit_sec: float = 3.0):
    """rate_limit_sec default of 3s is deliberately conservative - this is a
    small site, not a CDN. Increase, don't decrease, if in doubt."""
    leagues = leagues or LEAGUES
    seasons = seasons or season_codes()
    for season in seasons:
        for code, name in leagues.items():
            url = f"{BASE}/{season}/{code}.csv"
            acq.fetch(
                source="football_data_co_uk", resource_type="league_season", resource_key=f"{code}_{season}",
                url=url, dest_relpath=f"{code}/{season}.csv", licence_tag=LICENCE,
                rate_limit_sec=rate_limit_sec, min_size_bytes=50,
            )
            # a 404 here just means that league/season combination doesn't exist
            # (e.g. a league added to the site partway through its history) -
            # expected and fine, not a bug; it lands in the 'failed' status.


if __name__ == "__main__":
    print("This adapter is NOT run automatically in this sandbox - see "
          "acquisition/run_blocked_sources.py and docs/BLOCKED_SOURCE_COLLECTION.md")
