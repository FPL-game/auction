# Acquisition framework — maximum-data acquisition milestone

Resumable, provenance-tracked, rate-limited bulk downloader for every legitimately accessible football dataset this project has identified. Everything here is additive to the earlier milestones — the 7 approved pilot posts and their `review_pack/` are untouched (see "What this milestone does not touch" below).

## Quick reference

| I want to... | Run |
|---|---|
| See what's already downloaded and what's still queued/failed | `python3 acquisition/build_reports.py` |
| Resume/continue the GitHub-hosted bulk downloads (StatsBomb, Wyscout) | `python3 acquisition/run_statsbomb.py` and `python3 acquisition/run_wyscout.py` |
| Re-ingest OpenFootball or SkillCorner from their local clones | `python3 acquisition/adapters/openfootball.py` / `python3 acquisition/adapters/skillcorner.py` |
| Collect the network-blocked sources (must run outside this sandbox) | `python3 acquisition/run_blocked_sources.py --all` — see `docs/BLOCKED_SOURCE_COLLECTION.md` |
| Rebuild the entity inventory from whatever's in bronze (NOT identity resolution - see note below) | `python3 acquisition/build_entity_inventory.py` |
| Validate every downloaded match and refresh quarantine | `python3 acquisition/validate.py` |

## How resuming works

Every file fetched or ingested is recorded in `data/manifests/acquisition_state.db` (SQLite) with its source, resource type/key, URL, local path, HTTP status, file size, SHA-256, retrieval timestamp, attempt count, and licence tag. Re-running any adapter or entry-point script:

1. Checks the state DB for that exact (source, resource_type, resource_key, snapshot) row.
2. If it's `status='done'` **and** the file still exists on disk **and** its current hash still matches the recorded hash — skips it. No network call.
3. Otherwise fetches it, with retry/backoff on transient errors (429/500/502/503/504) and a hard failure recorded (not silently dropped) on anything else.

So: killing a download mid-run and re-running the same command is always safe — it picks up exactly where it left off. This is also why the two big downloads (StatsBomb, Wyscout) were simply run in the background and left running across the rest of this milestone's work, rather than needing to be babysat.

## Snapshot versioning

Bronze files live at `data/bronze/<source>/<snapshot>/<path>`, where `<snapshot>` is today's date (`YYYY-MM-DD`). A re-fetch on a later date writes to a new snapshot folder automatically — nothing from an earlier date is ever touched. A re-fetch on the *same* date that somehow produces different bytes for the same path is written alongside with a `.conflict-<hash8>` suffix rather than silently overwriting — see `acquisition/framework.py`'s `Acquirer.fetch()` for the exact logic.

## Layout

```
acquisition/
  framework.py              core: state DB, hashing, retry/backoff, quarantine, snapshot logic
  adapters/
    statsbomb.py             runnable here (GitHub)
    wyscout.py                runnable here (GitHub)
    openfootball.py           runnable here (GitHub, local clone + ingest)
    skillcorner.py            runnable here (GitHub, local clone + ingest; LFS/body-pose excluded)
    football_data_co_uk.py    NOT runnable here - see docs/BLOCKED_SOURCE_COLLECTION.md
    understat.py               NOT runnable here - experimental, local-only, see file docstring
    football_data_org.py      NOT runnable here - also needs a free API key
    fpl.py                     NOT runnable here
    wikidata.py                NOT runnable here
  run_statsbomb.py, run_wyscout.py     entry points for the two big GitHub bulk downloads
  run_blocked_sources.py               single entry point for the 5 blocked-source adapters
  build_entity_inventory.py             players/teams/competitions PER PROVIDER - an inventory, not
                                         identity resolution; alias_group_id stays NULL until a real
                                         matching pass exists
  validate.py                          per-match validation, writes to quarantine
  build_reports.py                     coverage_matrix.csv, download_manifest.parquet, failed_downloads.csv, disk usage

data/
  bronze/<source>/<snapshot>/   untouched raw files, exactly as retrieved
  silver/                        provider-specific cleaned/typed tables (Parquet) + identity tables
  gold/                          comparable, post-ready metric tables (Parquet/DuckDB) - not yet built this milestone, see below
  quarantine/                    validation failures, for inspection
  manifests/                     acquisition_state.db, coverage_matrix.csv, download_manifest.parquet,
                                  failed_downloads.csv, validation_results.csv, disk_usage_report.md
```

## What this milestone does not touch

Per instruction: `content-pipeline/posts/post_candidates.csv`, `content-pipeline/posts/claim_audit.csv`, `content-pipeline/review_pack/`, and the earlier `content-pipeline/bronze/` / `content-pipeline/silver/` / `content-pipeline/gold/` from the pilot milestones are **frozen** — nothing in `acquisition/` reads from or writes to them. The new `content-pipeline/data/` tree is entirely separate.

## What's deliberately not built yet

Gold-layer (comparable, cross-source, post-ready) tables for the newly acquired data are **not** part of this milestone's deliverables — the instruction was to stop after acquisition, validation, and the coverage report, before generating additional social posts. `<data-root>/gold/` exists as a directory for the next milestone.

**Architectural intent for that next step**, so it's written down before it's built: the Astro app (`fpl-game/auction`) should never read from `<data-root>/` directly, and should never need the raw archive at runtime. The pattern is gold layer → a small export script → a compact, committed JSON/CSV file under something like `content-pipeline/exports/` (or wherever the Astro app's own data-loading convention expects it) containing only the exact statistics a published post needs. That export script is the only thing that should ever copy data from outside the repo to inside it, and only ever small, curated, post-ready values — never bronze/silver rows.
