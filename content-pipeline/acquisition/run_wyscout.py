"""Entry point for the full Wyscout bulk download (1,941 matches). Resumable."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from acquisition.framework import Acquirer
from acquisition.adapters import wyscout

acq = Acquirer()
t0 = time.time()
matches = wyscout.list_all_matches()
print(f"{len(matches)} matches to fetch...")
wyscout.run(acq, matches)
elapsed = time.time() - t0
print(f"\nDone in {elapsed/60:.1f} min. Summary: {acq.summary()}")
acq.close()
