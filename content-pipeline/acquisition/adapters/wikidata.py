"""Wikidata adapter - for cross-provider identity metadata (players/teams/
competitions), feeding the identity-resolution tables in silver. NOT
RUNNABLE in this sandbox - query.wikidata.org is blocked by this session's
network egress policy.

Licence: Wikidata content is CC0 (public domain). The SPARQL endpoint's own
usage policy asks for a descriptive User-Agent (already set by the shared
Acquirer session) and reasonable query complexity/rate - this adapter sends
one query per batch, not one per entity.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from acquisition.framework import Acquirer

ENDPOINT = "https://query.wikidata.org/sparql"
LICENCE = "Wikidata - CC0 (public domain); respect the endpoint's query-complexity and rate guidance"

# Football player: instance-of human (Q5) with occupation association football
# player (Q937857), plus commonly-used external ID properties this project's
# identity table can key on. Extend this list as more provider IDs are needed.
PLAYER_QUERY = """
SELECT ?player ?playerLabel ?transfermarktId ?fbrefId ?wyscoutId ?opta_id WHERE {
  ?player wdt:P106 wd:Q937857 .
  OPTIONAL { ?player wdt:P3193 ?transfermarktId. }
  OPTIONAL { ?player wdt:P5750 ?fbrefId. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
LIMIT 5000
"""


def run(acq: Acquirer):
    acq.fetch(
        source="wikidata", resource_type="sparql_query", resource_key="players_batch1",
        url=f"{ENDPOINT}?query={PLAYER_QUERY.replace(chr(10), ' ')}&format=json",
        dest_relpath="players_batch1.json", licence_tag=LICENCE,
        rate_limit_sec=2.0, expect_json=True,
    )
    # Extend with team- and competition-entity queries the same way once the
    # player batch's coverage is reviewed - deliberately not all built at
    # once, since Wikidata's football-entity property coverage is uneven and
    # each query should be checked against a few known real entities before
    # trusting it at scale.


if __name__ == "__main__":
    print("This adapter is NOT run automatically in this sandbox - see "
          "acquisition/run_blocked_sources.py and docs/BLOCKED_SOURCE_COLLECTION.md")
