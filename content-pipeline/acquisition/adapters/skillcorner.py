"""SkillCorner Open Data adapter. Source: github.com/SkillCorner/opendata
(branch main). Licence: MIT.

An earlier milestone in this project cloned github.com/SkillCorner/opendata
with `GIT_LFS_SKIP_SMUDGE=1` (LFS pointer stubs only for the big tracking
files, real content for everything else) to /home/user/skillcorner/opendata,
and separately copied ONE representative match into
content-pipeline/bronze/skillcorner/. This adapter ingests ALL 20 matches'
non-LFS files (match.json, dynamic_events.csv, phases_of_play.csv per match,
plus the 3 season-aggregate CSVs, matches.json, LICENSE) from that full
clone - "all available SkillCorner non-LFS data", not just the one match
used for the pilot posts. Raw per-frame tracking (Git-LFS) and body-pose
data remain out of reach in this session; see docs/MANUAL_IMPORT_CONTRACTS.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from acquisition.framework import Acquirer

CLONE_DIR = Path("/home/user/skillcorner/opendata/data")
LICENCE = "SkillCorner Open Data - MIT licence"

# *_tracking_extrapolated.jsonl files are LFS pointer stubs in this clone
# (real content is the blocked Contract 1 in docs/MANUAL_IMPORT_CONTRACTS.md)
# - explicitly excluded here so a 133-byte pointer file is never mistaken
# for real tracking data in the bronze layer.
EXCLUDE_SUFFIXES = ("_tracking_extrapolated.jsonl",)


def run(acq: Acquirer):
    if not CLONE_DIR.exists():
        print(f"SKIP: {CLONE_DIR} not found")
        return
    files = [p for p in CLONE_DIR.rglob("*")
             if p.is_file() and not any(p.name.endswith(s) for s in EXCLUDE_SUFFIXES)
             and "bodypose" not in p.parts]
    for f in files:
        relpath = f.relative_to(CLONE_DIR)
        acq.ingest_local_file(
            source="skillcorner", resource_type="opendata", resource_key=str(relpath),
            src_path=f, dest_relpath=str(relpath), licence_tag=LICENCE,
            provenance_url=f"https://github.com/SkillCorner/opendata/blob/main/data/{relpath}",
        )
    print(f"skillcorner: {len(files)} files ingested (all 20 matches, non-LFS)")


if __name__ == "__main__":
    acq = Acquirer()
    run(acq)
    print(f"Summary: {acq.summary()}")
    acq.close()
