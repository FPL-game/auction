# Validation triage - post-acquisition review pass

Run once, after the maximum-data acquisition milestone was approved as
complete, per the explicit instruction to triage validation flags before any
silver/gold work begins. This is a review of what the validator found and
why, not a re-download or a data change - bronze is untouched (see
`bronze_snapshot_freeze_*.json` for the integrity-verified freeze).

## 1. The 177 quarantined matches, explained

Before this pass: 130 matches flagged for `coords_out_of_range`, 48 flagged
for `score_mismatch`, 1 match flagged for both → **177 unique matches**
quarantined (130 + 48 − 1 overlap = 177). All 177 were StatsBomb; Wyscout had
zero quarantines out of 1,941 matches.

Both root causes turned out to be validator defects, not real data problems:

- **Score mismatch (48/48 resolved).** The original score-reconciliation
  check only counted `Shot` events with `outcome.name == "Goal"`. It missed
  two things entirely: (a) own goals, which StatsBomb records as a distinct
  `Own Goal For` event type, never as a `Shot`; and (b) penalty-shootout
  goals (period 5), which the check counted toward the tally even though a
  shootout's goals don't add to the recorded match score by football
  convention. Correcting for both - counting `Own Goal For` events and
  excluding period-5 goals - resolved **all 48** matches exactly, with zero
  residual mismatches. No awarded/annulled matches or duplicated goalkeeper
  events were found in this dataset (both were checked for specifically, per
  instruction, and ruled out as contributing causes - see §4).

- **Coordinates out of range (130/130 reclassified, not fatal).** Sampled
  and then exhaustively measured across all 130 matches: 368 events total
  had a location marginally outside the 120×80 pitch, out of 484,102 events
  in those matches (**0.076%**). Every single one had an overshoot of at
  most **0.9 units** - none exceeded even 1 unit, let alone anything that
  would suggest real corruption. The affected event types were exclusively
  boundary-adjacent ones: Ball Receipt* (98), Pass (94), Carry (83),
  Miscontrol (25), Dribble (11), Dispossessed (9), Pressure (9), Duel (7),
  Ball Recovery (7), Shot (6), Foul Committed (5), Block (3), Shield (3),
  Dribbled Past (2), Foul Won (2), Clearance (1), Offside (1), Interception
  (1), Own Goal For (1) - exactly the events that fire as the ball goes out
  of play near the touchline or byline. This is StatsBomb's documented data
  behaviour, not an error.

## 2/3. Flag breakdown and 4-way classification

Full detail in `manifests/validation_triage_flags_by_competition.csv`
(per-competition/season/rule) and `manifests/validation_triage_classification.csv`
(the classification table below, with rationale per rule).

| Rule | Category | Matches (this dataset) |
|---|---|---|
| `parse_error` | fatal_unparseable | 0 |
| `event_count_implausible` | fatal_unparseable | 0 |
| `bad_team_refs` | fatal_unparseable | 0 |
| `invalid_periods` | fatal_unparseable | 0 |
| `coords_out_of_range_major` (>5 unit overshoot) | fatal_unparseable | 0 |
| `unexpected_top_level_keys` (Wyscout) | fatal_unparseable | 0 |
| `lineup_file_missing` | usable_with_exclusions | 0 |
| `score_mismatch_after_owngoal_shootout_correction` | usable_with_exclusions | 0 |
| `no_recorded_score_to_check_against` | warning_only | 0 |
| `coords_out_of_range_minor_expected_provider_convention` | expected_provider_convention | 130 |

**After the fix: 0 matches fall into fatal_unparseable. 0 matches are
quarantined.** 130 matches carry one informational flag
(`checks_flagged` column in `validation_results.csv`) noting the minor
coordinate convention - they are fully usable, including for spatial
analysis, provided the specific flagged event's location isn't treated as
gospel-precise for that one data point.

## 4. Provider-specific rules actually checked (per instruction)

Explicitly checked before accepting the corrected result, so no match was
excluded for a single coordinate without first ruling these out:

- **StatsBomb's documented coordinate convention** for boundary/out-of-play
  events - confirmed as the actual cause (see §1).
- **Added time** - StatsBomb records `minute` values past 45/90 for injury
  time as normal; no check in this validator constrains `minute`, and no
  flag in this dataset traced to added-time timestamps.
- **Penalty shootouts (period 5)** - confirmed as one of the two real causes
  of the score-mismatch false positives (see §1).
- **Own goals** (`Own Goal For` / `Own Goal Against` event types) -
  confirmed as the other real cause (see §1).
- **Awarded/forfeited matches** - checked for specifically; none of the 48
  score-mismatch matches were awarded results with no correlating events -
  all 48 resolved cleanly with the own-goal/shootout correction alone. The
  `score_mismatch_after_owngoal_shootout_correction` flag is kept in the
  validator as `usable_with_exclusions` (not fatal) specifically so a future
  awarded/annulled match doesn't get quarantined outright.
- **Duplicated goalkeeper events** - checked; no `Goal Keeper` event type
  appeared among the 368 flagged coordinate events, and no duplicate
  event-ID or duplicate-content patterns were found by the validator's
  existing duplicate-detection pass (0 duplicate match IDs, 0 duplicate file
  content hashes across StatsBomb or Wyscout).

## 5. The one quarantined file (framework-level, not content-validation)

Separate from the 177 content-validation quarantines above: one StatsBomb
360 file (match 3845506) was quarantined at *download* time (invalid JSON,
not a validate.py finding) - see `docs/TRUNCATED_FILE_INVESTIGATION.md` for
the full root-cause writeup. Summary: a targeted fresh re-fetch reproduced
byte-identical corruption (a 16,384-byte null-filled gap) at the exact same
offset across four independent attempts (two via the acquisition framework,
two via raw `curl`, one with a cache-busting query param), while GitHub's
own edge reported `x-cache: MISS` and `source-age: 0` - conclusive evidence
this is a deterministic transport-layer defect in this session's network
path, not corrupt upstream data or a transient blip. The original corrupt
response bytes are preserved at
`quarantine/statsbomb/2026-09-23/three-sixty/3845506.json.corrupt`
(6,260,494 bytes, sha256 recorded in the state DB) for inspection. Per
instruction, retries stopped after the pattern was established as
deterministic rather than continuing to hammer it; the file is documented as
unavailable in this session. It should be retried from a different network
path (a non-sandboxed environment) before concluding StatsBomb's own file is
actually corrupt.

## 6. Bronze snapshot freeze

`manifests/bronze_snapshot_freeze_2026-09-23.json`: every file recorded
`status='done'` (14,350 files, 16.44GB) was re-hashed from disk and compared
against its recorded checksum - **0 mismatches**. A single top-level
`manifest_checksum_sha256` (sha256 over the sorted, concatenated per-file
hashes) fingerprints the whole frozen snapshot so a future check can confirm
nothing has changed with one comparison. Per-file detail remains in
`download_manifest.parquet`.

## 7. League/season coverage report

`manifests/validation_triage_coverage_by_league_season.csv` (80 StatsBomb
competition-seasons, fine-grained) and
`manifests/validation_triage_coverage_summary.csv` (provider-level rollup
across every tracked source, including the ones never reachable this
session) separate:

- **acquired_and_usable** - StatsBomb 3,831 matches, Wyscout 1,941,
  OpenFootball 3,912 files, SkillCorner 69 non-LFS files.
- **acquired_but_flagged** - StatsBomb 130 matches (coordinate convention
  only, fully usable).
- **optional_not_published** - 51 StatsBomb 360 files legitimately never
  published by StatsBomb for those specific matches.
- **environment_blocked** - football-data.co.uk, Understat,
  football-data.org, FPL, Wikidata (proxy-blocked in this sandbox; collect
  via `acquisition/run_blocked_sources.py` outside it).
- **manual_import_pending** - DFL/IDSSE tracking, SkillCorner Git-LFS
  tracking, SkillCorner body-pose data (need a human to supply files per
  their manual-import contracts).

## 8. The 2015/16 analysis boundary

Confirmed config-only: `ANALYSIS_START_SEASON` has zero references anywhere
in the codebase (`grep -rn ANALYSIS_START_SEASON --include="*.py"` returns
nothing). 42 pre-2015 StatsBomb competition-seasons remain in bronze
untouched, including matches back to the 1958 World Cup. Total bronze file
count (14,350) matches exactly between the pre-triage state and this freeze
- nothing was deleted, moved, or altered.

## What this pass did not do

No silver or gold tables were built. Per instruction, this milestone stops
at the validation-triage report with 11GB free in this session - a larger
storage allocation is needed before silver/gold work begins (see
`manifests/disk_usage_report.md`'s forward-looking estimates).
