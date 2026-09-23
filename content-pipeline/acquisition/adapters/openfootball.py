"""OpenFootball adapter. Source: github.com/openfootball/* (multiple repos).
Licence: CC0 1.0 Universal (public domain) - verified by reading each repo's
own LICENSE file directly, not assumed from the index that pointed here.

Repos selected (per the milestone's "relevant league, cup and international
repositories" scope - not an attempt at every openfootball repo, which
number in the dozens):
- football.json: major European leagues, current + historical seasons
- world: results for leagues openfootball's own README flags as otherwise
  rare open data (Africa, further Asia, MLS, etc.)
- worldcup: every men's World Cup 1930-2026
- south-america: Argentina/Brazil/Colombia/etc. + Copa Libertadores

Repos are `git clone`d (not HTTP-fetched file by file - they're small, a
clone is simpler and these aren't Git-LFS repos), then every non-.git file
is ingested into the bronze layer with the same hashing/provenance/
never-overwrite discipline as the HTTP-fetched sources.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from acquisition.framework import Acquirer

REPOS = ["football.json", "world", "worldcup", "south-america"]
CLONE_ROOT = Path("/home/user/openfootball")
LICENCE = "CC0 1.0 Universal (public domain) - verified by reading each repo's own LICENSE file"


def run(acq: Acquirer):
    for repo in REPOS:
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
