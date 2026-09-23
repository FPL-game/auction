# content-pipeline

An evidence-backed football-data pipeline for generating social-post candidates — plan and proof-of-concept stage. This is a **personal-study project**, not a commercial service; nothing here publishes or posts automatically.

## Status

Milestone 1 (manifests/inventory) and milestone 2 (proof-of-concept with real numbers) are done for two sources: **StatsBomb Open Data** and **SkillCorner Open Data**. DFL/IDSSE is documented but blocked in this sandboxed environment (network policy, not licensing — see below). Driblab Open Data is deliberately disabled (no licence found in its repo). Everything is stopped here for human review before scaling up, per instruction.

Read first:
- [`docs/CAPABILITY_MATRIX.md`](docs/CAPABILITY_MATRIX.md) — per-source licence/access audit
- [`docs/METRIC_REGISTRY.yaml`](docs/METRIC_REGISTRY.yaml) — every metric this pipeline can or can't produce, and why
- [`docs/SOURCE_INVENTORY.md`](docs/SOURCE_INVENTORY.md) — exact coverage of what was actually downloaded this session
- [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) — architecture and the open_demo/licensed_live mode split

## Setup

```bash
cd content-pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install pandas duckdb pyarrow matplotlib mplsoccer requests
```

## What's here

```
bronze/           raw, as-fetched files, checksummed and dated — see bronze/RETRIEVAL_LOG.md
scratch/           intermediate audit CSVs (the exact rows behind every post_candidates.csv claim)
posts/
  post_candidates.csv   the 7 proof-of-concept post candidates, real numbers, full audit trail
charts/            the 6 PNG visuals backing those posts
docs/               capability matrix, metric registry, source inventory
```

Silver (cleaned/standardised tables) and gold (the full DuckDB/Parquet metric warehouse) are designed in `IMPLEMENTATION_PLAN.md` but not yet built — the proof-of-concept numbers so far were computed directly from bronze with pandas, which is enough to prove the metrics are real and reproducible, but isn't yet the durable, queryable layer the full plan calls for. That's the next phase, pending your review of this proof-of-concept.

## Licensing — read before reusing anything here

- **StatsBomb**: free (open data), but you must credit "StatsBomb" as the source and use their logo per their Media Pack. Non-commercial/research use.
- **SkillCorner**: MIT licence — very permissive, credit given anyway.
- **DFL/IDSSE**: CC-BY 4.0 — not currently used (see below), but if you supply the files manually, you must name the Deutsche Fußball Liga and cite the Bassek et al. 2025 paper (full citation in `docs/SOURCE_INVENTORY.md`).
- **Driblab**: disabled — its open-data repo has no licence at all.

## Known limitations (read before trusting a number)

1. **SkillCorner's raw per-frame tracking could not be downloaded in this session** (Git-LFS objects are only reachable for repos under this project's own GitHub org). Every SkillCorner-derived post here uses SkillCorner's own **event- and phase-level derived fields** (EPV, pressure, line-breaks, team width/length at phase boundaries) — real, provider-computed, but not raw positions. Nothing claiming continuous tracking, live speed traces, or pitch control was produced, because that data isn't in hand.
2. **DFL/IDSSE could not be downloaded at all** in this sandbox — every hosting location (Hugging Face, Figshare, Nature, the DOI resolver) is blocked by this session's network policy. Not a licence issue; see `docs/SOURCE_INVENTORY.md` for the exact files needed if you want to supply them manually.
3. **SkillCorner season aggregates cover the whole 2024/25 A-League season** (up to 29 matches per player); the raw/event-level tracking data covers only 20 of those matches. Don't conflate the two when citing a number.
4. **One SkillCorner match (`1953632`) has a misleading `status: "not_started"` label** in the manifest despite having a complete file set and a real final score — verified by inspection, flagged for anyone else working from this manifest.
5. **StatsBomb's full open-data repo could not be `git clone`d in this session** — it stalled indefinitely after the initial handshake with zero bytes transferred. Targeted per-file fetches via `raw.githubusercontent.com` worked reliably instead; that's the pattern used throughout, and the one to keep using.
6. Every "modelled" number (xG, EPV, pressure/space-constraint ratings, xThreat) is exactly that — a provider's model output, not a measured fact. `post_candidates.csv`'s `methodology` and `caveat` columns say so for each row.

## Reproducing a post_candidates.csv row

Every row's `source_url` points at the exact bronze file; the matching `scratch/*_audit.csv` file has the underlying rows the number was computed from. Nothing in `post_candidates.csv` was typed by hand without a row behind it.
