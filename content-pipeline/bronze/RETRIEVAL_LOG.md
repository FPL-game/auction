# Bronze layer retrieval log

Immutable, as-fetched. Checksums in `retrieval_checksums.sha256`.

| Retrieved (UTC) | Source | Method | Files |
|---|---|---|---|
| 2026-09-23 | StatsBomb Open Data (github.com/statsbomb/open-data, branch `master`) | Targeted `raw.githubusercontent.com` fetches (full-repo clone stalled indefinitely in this session — see IMPLEMENTATION_PLAN.md) | competitions.json; matches.json for comp 43/season 106 (WC2022) and comp 43/season 3 (WC2018); events+lineups for match 8658 (WC2018 Final) and match 3869685 (WC2022 Final); 360 frames for match 3869685 |
| 2026-09-23 | SkillCorner Open Data (github.com/SkillCorner/opendata, branch `main`) | `git clone --depth 1` (non-LFS files only — raw per-frame tracking is LFS-gated and out of reach in this session, see IMPLEMENTATION_PLAN.md) | matches.json (20-match manifest); 3 season-aggregate CSVs (physical/passing/off-ball-run, ~407 players); LICENSE; upstream README; full match/dynamic_events/phases_of_play for match 1874553 (representative match) |

Not retrieved this session (environment-blocked, not licence-blocked): DFL/IDSSE (huggingface.co, figshare.com, doi.org, nature.com all return policy-denied 403s from this session's egress proxy). See docs/CAPABILITY_MATRIX.md.

Not retrieved this session (deliberately deferred per milestone-2 scope): SkillCorner raw per-frame tracking for any match, SkillCorner body-pose data, Driblab Open Data (kept disabled — no licence found).
