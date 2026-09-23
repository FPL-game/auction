# Collecting the network-blocked sources

Five sources are built but not run in this sandboxed session, because their hosts are blocked by this session's network egress policy: football-data.co.uk, Understat, football-data.org, FPL, and Wikidata. This is a session/environment restriction, not a licensing problem — see `docs/CAPABILITY_MATRIX.md`'s environment note.

## The one command

```bash
cd content-pipeline
python3 -m venv .venv && source .venv/bin/activate    # first time only
pip install -r requirements.txt                        # first time only
python3 acquisition/run_blocked_sources.py --all
```

Run it on any machine with normal internet access — your laptop, a cloud VM, anywhere outside this sandbox. It writes into the same `data/bronze/`, `data/manifests/acquisition_state.db` layout this project already uses, so the results merge straight back in; commit and push the resulting `data/` changes (or hand them back to this session) the same way as everything else in this repo.

**It is safe to interrupt and re-run.** Progress is tracked in `data/manifests/acquisition_state.db` — anything already downloaded (verified by its saved hash) is skipped, not re-fetched.

## Running one source at a time

```bash
python3 acquisition/run_blocked_sources.py --source fpl
python3 acquisition/run_blocked_sources.py --source football_data_co_uk
python3 acquisition/run_blocked_sources.py --source understat
python3 acquisition/run_blocked_sources.py --source wikidata
FOOTBALL_DATA_ORG_API_KEY=your_key_here python3 acquisition/run_blocked_sources.py --source football_data_org
```

## Per-source notes

| Source | Key needed? | Rate limit (built in) | Notes |
|---|---|---|---|
| FPL | No | 1s/request | Same public API the repo's own `scripts/update-fpl-data.mjs` uses. |
| football-data.co.uk | No | 3s/request | Pulls every league × season combination in `acquisition/adapters/football_data_co_uk.py`'s `LEAGUES`/`season_codes()` — a 404 on a combination that doesn't exist (e.g. a league not yet tracked in an early season) is expected, not an error. |
| football-data.org | **Yes** — free signup at [football-data.org/client/register](https://www.football-data.org/client/register) | 6.5s/request (their free-tier 10 req/min limit) | Export `FOOTBALL_DATA_ORG_API_KEY` before running. |
| Understat | No | 8s/request | **Experimental, local-only** — no official API or published bulk-access terms exist for this site. Built strictly for personal, non-redistributed use: public pages only, no login/paywall/CAPTCHA targeted, permanent local caching so a completed match is never re-fetched, and it deliberately **stops** (doesn't retry) the moment a response looks like a block page, a 403, or a 429 — see `UnderstatBlockedError` in `acquisition/adapters/understat.py`. Review that file before running it if you have any doubt about current terms. |
| Wikidata | No | one query per batch | For identity-resolution metadata (cross-provider player/team IDs). Content is CC0. |

## What none of this does

No CAPTCHA solving, no login automation, no proxy rotation, no access-control circumvention, anywhere in these five adapters. If a source starts actively blocking requests, the adapter is built to stop and report that, not find a way around it.
