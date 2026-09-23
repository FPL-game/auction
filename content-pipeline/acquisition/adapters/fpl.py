"""Fantasy Premier League public API adapter. NOT RUNNABLE in this sandbox -
fantasy.premierleague.com is blocked by this session's network egress policy
(the production auction-league app in this same repo reaches it fine from
GitHub Actions, which runs on a different network to this interactive
sandbox - see docs/CAPABILITY_MATRIX.md).

No key needed; unofficial but broadly used by hobbyist projects, including
this repo's own scripts/update-fpl-data.mjs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from acquisition.framework import Acquirer

BASE = "https://fantasy.premierleague.com/api"
LICENCE = "Unofficial public FPL API - no formal ToS; broadly used for non-commercial fan projects"


def run(acq: Acquirer):
    acq.fetch(
        source="fpl", resource_type="bootstrap", resource_key="bootstrap-static",
        url=f"{BASE}/bootstrap-static/", dest_relpath="bootstrap-static.json",
        licence_tag=LICENCE, rate_limit_sec=1.0, expect_json=True,
    )
    acq.fetch(
        source="fpl", resource_type="fixtures", resource_key="fixtures",
        url=f"{BASE}/fixtures/", dest_relpath="fixtures.json",
        licence_tag=LICENCE, rate_limit_sec=1.0, expect_json=True,
    )
    # Per-player history (element-summary) is a separate call per player id -
    # read bootstrap-static's 'elements' array first to get the full id list,
    # then loop; deliberately not hardcoded here since it changes every season.


if __name__ == "__main__":
    print("This adapter is NOT run automatically in this sandbox - see "
          "acquisition/run_blocked_sources.py and docs/BLOCKED_SOURCE_COLLECTION.md")
