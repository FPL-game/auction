"""OpenFootball adapter. Source: github.com/openfootball/* (multiple repos).
Licence: CC0 1.0 Universal (public domain) - verified by reading each repo's
own LICENSE file directly, not assumed from the index that pointed here.

Repos, in two batches:

Batch 1 (first pass): football.json (major European leagues), world (Africa/
further Asia/MLS etc - openfootball's own README flags these as otherwise
rare open data), worldcup (every men's World Cup 1930-2026), south-america
(Argentina/Brazil/Colombia/etc + Copa Libertadores).

Batch 2 (expanded inventory, added per instruction - country-specific and
umbrella competition repos that overlap in coverage with batch 1's
multi-league/multi-country repos by design, e.g. england's Premier League
data and football.json's England section describe a lot of the same real
matches from different repos): england, deutschland, espana, italy, europe,
champions-league, euro, internationals, clubs, club-worldcup, copa-america,
north-america-gold-cup. All 12 verified CC0 1.0 Universal by reading each
repo's own LICENSE file directly (not assumed).

Repos are `git clone`d (not HTTP-fetched file by file - they're small, a
clone is simpler and these aren't Git-LFS repos), then every non-.git file
is ingested into the bronze layer with the same hashing/provenance/
never-overwrite discipline as the HTTP-fetched sources. Cross-repo overlap
(the same real match appearing in e.g. both `england` and `football.json`)
is EXPECTED and is deliberately not deduplicated here - each repo's raw
files are kept with their own separate provenance; overlap is detected and
reported (not merged) by acquisition/validate.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from acquisition.framework import Acquirer

BATCH_1 = ["football.json", "world", "worldcup", "south-america"]
BATCH_2 = ["england", "deutschland", "espana", "italy", "europe", "champions-league",
           "euro", "internationals", "clubs", "club-worldcup", "copa-america",
           "north-america-gold-cup"]
REPOS = BATCH_1 + BATCH_2
CLONE_ROOT = Path("/home/user/openfootball")
LICENCE = "CC0 1.0 Universal (public domain) - verified by reading each repo's own LICENSE file"


def run(acq: Acquirer, repos: list = None):
    repos = repos or REPOS
    for repo in repos:
        repo_dir = CLONE_ROOT / repo
        if not repo_dir.exists():
            print(f"SKIP {repo}: not cloned")
            continue
        files = [p for p in repo_dir.rglob("*") if p.is_file() and ".git" not in p.parts]
        for f in files:
            relpath = f.relative_to(repo_dir)
            acq.ingest_local_file(
                source="openfootball", resource_type=repo, resource_key=str(relpath),
                src_path=f, dest_relpath=f"{repo}/{relpath}", licence_tag=LICENCE,
                provenance_url=f"https://github.com/openfootball/{repo}/blob/main/{relpath}",
            )
        print(f"{repo}: {len(files)} files ingested")


if __name__ == "__main__":
    acq = Acquirer()
    run(acq)
    print(f"\nSummary: {acq.summary()}")
    acq.close()
