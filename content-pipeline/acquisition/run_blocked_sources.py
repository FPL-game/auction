#!/usr/bin/env python3
"""
Single entry point for every source this sandbox cannot reach:
football-data.co.uk, Understat, football-data.org, FPL, Wikidata.

Run this OUTSIDE the sandbox, on a machine with normal internet access:

    python3 acquisition/run_blocked_sources.py --all

or one source at a time:

    python3 acquisition/run_blocked_sources.py --source fpl
    python3 acquisition/run_blocked_sources.py --source football_data_co_uk
    python3 acquisition/run_blocked_sources.py --source understat
    python3 acquisition/run_blocked_sources.py --source football_data_org   # needs FOOTBALL_DATA_ORG_API_KEY
    python3 acquisition/run_blocked_sources.py --source wikidata

Setup (once):
    cd content-pipeline
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt

Safe to interrupt (Ctrl-C) and re-run at any time - every fetch is recorded
in data/manifests/acquisition_state.db, and already-'done' files (verified
by hash) are skipped on the next run. All requests are cached to
data/bronze/ permanently; nothing is ever re-fetched for data that hasn't
changed (a completed historical match, for instance).

Rate limits are conservative by design (built into each adapter, not a flag
you need to tune): football-data.co.uk ~3s/request, Understat 8s/request,
football-data.org ~6.5s/request (its own 10-req/min free-tier limit), FPL
1s/request, Wikidata one batched query at a time. None of this does
CAPTCHA-solving, login automation, proxy rotation, or anything else meant to
get around an access control - if a source ever starts blocking, the
adapter is built to stop (see understat.py's UnderstatBlockedError) rather
than find a way around it.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from acquisition.framework import Acquirer
from acquisition.adapters import football_data_co_uk, understat, football_data_org, fpl, wikidata

ADAPTERS = {
    "football_data_co_uk": football_data_co_uk.run,
    "understat": understat.run,
    "football_data_org": football_data_org.run,
    "fpl": fpl.run,
    "wikidata": wikidata.run,
}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", choices=list(ADAPTERS.keys()), help="Run just this one source")
    p.add_argument("--all", action="store_true", help="Run every blocked-source adapter in sequence")
    args = p.parse_args()

    if not args.source and not args.all:
        p.print_help()
        return

    acq = Acquirer()
    sources = [args.source] if args.source else list(ADAPTERS.keys())
    for name in sources:
        print(f"\n=== {name} ===")
        try:
            ADAPTERS[name](acq)
        except Exception as e:
            print(f"STOPPED {name}: {e}")
        print(f"Running totals: {acq.summary()}")
    acq.close()


if __name__ == "__main__":
    main()
