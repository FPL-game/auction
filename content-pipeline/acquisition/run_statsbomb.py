"""Entry point for the full StatsBomb bulk download (~8,400 files).
Resumable: safe to Ctrl-C and re-run, or re-run after this process is killed
- already-'done' files (verified by hash) are skipped."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from acquisition.framework import Acquirer
from acquisition.adapters import statsbomb

acq = Acquirer()
t0 = time.time()
print("Fetching competitions + match lists...")
competitions, match_lists, total_matches, total_360 = statsbomb.plan(acq)
print(f"{total_matches} matches, {total_360} with 360. Starting full download...")
statsbomb.run(acq, match_lists, competitions)
elapsed = time.time() - t0
print(f"\nDone in {elapsed/60:.1f} min. Summary: {acq.summary()}")
acq.close()
