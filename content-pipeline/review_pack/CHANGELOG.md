# Change log — QA revision

Changes made in this pass, in response to a review of the previous version of this review pack. Nothing was scaled up (no new posts, no larger dataset) — this is corrections only.

## 1. Fixed: Mbappé 360 story used the wrong source product

**Before:** used the event's embedded `shot.freeze_frame` (has player names) and reported 4.05m, on the basis that it had player identity to report.

**Why that was wrong:** `shot.freeze_frame` and the standalone `data/three-sixty/{match}.json` file are two distinct StatsBomb source products, not two views of the same thing. Choosing one because it happened to be more convenient to caption (named players) wasn't a defensible reason when the candidate specifically exists to demonstrate StatsBomb 360.

**Now:** the standalone `three-sixty` file — the actual StatsBomb 360 product — is canonical. Published value: **3.41m**, opponents labelled generically (`#1`–`#7`, `GK`), captioned as "StatsBomb 360" specifically. The embedded field's 4.05m value is retained in `claim_audit.csv` and a separate, unpublished silver table (`statsbomb_360_freeze_frames_shot_embedded`) as a disclosed reconciliation reference, clearly marked "not published as a claim." Chart 2 was regenerated to match.

## 2. Fixed: team-width average wasn't reproducible between pandas and SQL

**Before:** an earlier pandas prototype and the DuckDB gold query disagreed by up to 0.3m on the same numbers, silently.

**Root cause, now documented:** 19 of the match's 423 possession phases are missing either `team_in_possession_width_start` or `_end`. Pandas' `.mean(axis=1)` quietly used whichever single value was present for those rows; DuckDB's `avg((start+end)/2.0)` treats a NULL in either input as making the whole row NULL, and `avg()` skips NULLs — so those 19 phases were silently dropped from the SQL version instead of repaired.

**Now:** the SQL behaviour (exclude, don't repair) is the documented canonical rule. A regression test (`pipeline/tests/test_team_width_null_handling.py`) asserts it against both a synthetic fixture and the real 423-phase file (19 excluded, 404 used — locked in as an assertion so a future data or code change that breaks this gets caught). The gold table now reports `n_phases_used` alongside `n_phases_total` so this is visible, not just internally consistent. Chart 6 and the caption were regenerated from these exact canonical figures (39.22m → 45.35m Brisbane, rounds to 39.2/45.4; 48.46m → 43.55m Adelaide).

## 3. Amended: DFL checksum documentation

`docs/DFL_MANUAL_IMPORT.md` now states explicitly that the self-generated SHA-256 manifest provides *integrity checking after import* (detects later corruption/tampering) and explicitly does **not** authenticate the files against the publisher — no publisher checksum exists to compare against. No behavioural change, just closing a wording gap that could have overstated what the manifest proves.

## 4. Strengthened: Wyscout validation now covers all 7 competition groups

**Before:** one match (Liverpool 4-0 Arsenal, Premier League) was validated, and the source inventory's wording risked reading as if that validated the whole 1,941-file dataset.

**Now:** one representative match per competition group (all 7: Premier League, Ligue 1, Serie A, La Liga, Bundesliga, World Cup 2018, UEFA Euro 2016) was pulled and run through 6 checks each: schema/event-count plausibility, coordinate range + attacking-direction clustering, valid match periods + plausible timestamps, all event team references resolving, goal counts matching the real final score, and a successful `kloppy` load. **All 7 pass all 6 checks** (`pipeline/validate_wyscout.py`, `scratch/wyscout_multi_competition_validation.csv`).

**A real bug was found and fixed while building this check**: the first version of the goal-count check only looked at `eventName == 'Shot'`, which missed penalty goals and direct free-kick goals (both distinct Wyscout event types) — 6 of 7 matches initially failed. Fixed to count any goal-tagged event that isn't the goalkeeper's paired "Save attempt" record, which is robust rather than enumerating every possible scoring event name. Documented in `docs/SOURCE_INVENTORY.md` and the validation script's own comments.

`docs/SOURCE_INVENTORY.md` now explicitly states this is 7 of 1,941 matches (0.4%) validated — a format/schema consistency check, not proof every remaining file is individually correct.

## Files touched

- `pipeline/build_silver_events.py` — canonical 360 source, reconciliation-only table added
- `pipeline/build_gold.py` — canonical 360 query, canonical team-width query with `n_phases_used`
- `pipeline/tests/test_team_width_null_handling.py` — new regression test
- `pipeline/validate_wyscout.py` — new, 7-competition validation script
- `docs/DFL_MANUAL_IMPORT.md` — checksum scope clarified
- `docs/SOURCE_INVENTORY.md` — Wyscout section rewritten for 7-match validation
- `posts/post_candidates.csv`, `posts/claim_audit.csv` — rows 2 and 7 updated
- `charts/02_wc2022_final_mbappe_360.png`, `charts/06_skillcorner_team_shape.png` — regenerated
- `review_pack/` — regenerated to match all of the above
