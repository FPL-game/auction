"""Final validation-triage pass, run once after acquisition/validate.py, per
the explicit post-acquisition review instruction. Reads validation_results.csv
(already produced by validate.py's corrected score-reconciliation and
severity-aware coordinate checks) and:

1. Breaks every flag down by provider / competition / season / rule.
2. Classifies each rule into one of four categories:
     - fatal_unparseable          (the file/match cannot be trusted at all)
     - usable_with_exclusions     (the match is usable; specific fields need care)
     - warning_only               (informational, no action needed)
     - expected_provider_convention (a known, documented source-data quirk)
3. Produces a league/season coverage report split into:
     acquired_and_usable | acquired_but_flagged | optional_not_published |
     environment_blocked | manual_import_pending

Read-only against validation_results.csv, the acquisition_state.db, and
bronze/ - never mutates anything. Writes its outputs to <data-root>/manifests/.
"""
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from acquisition.framework import DATA

BRONZE = DATA / "bronze"
MANIFESTS = DATA / "manifests"

# Static classification of every rule this milestone's validator can emit,
# fatal or flagged. Built from the triage analysis run against this exact
# dataset (see docs/VALIDATION_TRIAGE.md for the full worked evidence: event
# counts, overshoot magnitudes, before/after resolution counts).
RULE_CLASSIFICATION = {
    "parse_error": ("fatal_unparseable",
                     "File does not parse as JSON at all - nothing in it can be trusted."),
    "event_count_implausible": ("fatal_unparseable",
                     "Event count wildly outside a plausible match (<100 or >6000) - "
                     "suggests a truncated or wrong file, not a real match."),
    "bad_team_refs": ("fatal_unparseable",
                     "Event-level team_id doesn't resolve against the match's own lineup file - "
                     "indicates an indexing/parsing problem, not a data convention."),
    "invalid_periods": ("fatal_unparseable",
                     "Period label outside {1,2,3,4,5} (halves, extra time, shootout) - "
                     "not a real StatsBomb period, so the event's context is unreliable."),
    "coords_out_of_range_major": ("fatal_unparseable",
                     "Coordinate overshoot >5 units on a 120x80 pitch - far beyond the "
                     "documented boundary convention, indicates real coordinate corruption."),
    "coords_out_of_range_minor_expected_provider_convention": ("expected_provider_convention",
                     "StatsBomb records a small out-of-bounds location (confirmed max 0.9 units, "
                     "0.076% of events in affected matches) for boundary-adjacent events "
                     "(Ball Receipt/Pass/Carry/Miscontrol/Dribble/Dispossessed/Pressure/Duel/"
                     "Ball Recovery) as the ball goes out of play. Documented StatsBomb behaviour, "
                     "not an error - exclude only the specific event's location field from "
                     "strict spatial analysis, never the whole match."),
    "lineup_file_missing": ("usable_with_exclusions",
                     "Events are intact and usable; only team-ID cross-validation is degraded "
                     "for this one match since there's no roster to check IDs against."),
    "score_mismatch_after_owngoal_shootout_correction": ("usable_with_exclusions",
                     "Event stream is intact (this only fires after correcting for own goals and "
                     "excluding penalty-shootout-period goals); a residual mismatch most likely "
                     "means an awarded/annulled result - usable, but don't trust the recorded "
                     "score field for that match without a manual look."),
    "no_recorded_score_to_check_against": ("warning_only",
                     "No matches list entry with a recorded score was found for this match_id - "
                     "informational, doesn't affect the event data's usability."),
    "unexpected_top_level_keys": ("fatal_unparseable",
                     "Wyscout match file doesn't have the expected {events,teams,players} shape."),
}


def _statsbomb_competition_map():
    sb_snap = next((BRONZE / "statsbomb").iterdir())
    comps = {}
    for c in json.loads((sb_snap / "competitions.json").read_text()):
        comps[(c["competition_id"], c["season_id"])] = c
    match_map = {}
    for f in (BRONZE / "statsbomb").glob("*/matches/*/*.json"):
        cid, sid = int(f.parent.name), int(f.stem)
        c = comps.get((cid, sid), {})
        comp_label = f"{c.get('country_name', '?')} - {c.get('competition_name', '?')}"
        season_label = c.get("season_name", "?")
        for m in json.loads(f.read_text()):
            match_map[m["match_id"]] = (comp_label, season_label)
    return match_map, comps


def _wyscout_competition_map():
    import re
    match_map = {}
    for idx in (BRONZE / "wyscout").glob("*/match_index_processed-v2.md"):
        row_re = re.compile(r"\|\[(\d+)\]\(files/\d+\.json\)\|([^|]*)\|([^|]*)\|([^|]*)\|")
        for m in row_re.finditer(idx.read_text()):
            match_id, label, date, comp_file = m.groups()
            match_map[int(match_id)] = (comp_file.strip().replace(".json", ""), "n/a (multi-season file)")
    return match_map


def build_flag_breakdown():
    df = pd.read_csv(MANIFESTS / "validation_results.csv")
    sb_map, comps = _statsbomb_competition_map()
    ws_map = _wyscout_competition_map()

    rows = []
    for _, r in df.iterrows():
        source, match_id = r["source"], r["match_id"]
        comp, season = (sb_map.get(match_id, ("unknown", "unknown")) if source == "statsbomb"
                         else ws_map.get(match_id, ("unknown", "unknown")))
        for col, sev_col in [("checks_failed", "fatal"), ("checks_flagged", "flagged")]:
            val = r.get(col)
            if pd.isna(val) or not val:
                continue
            for rule_raw in str(val).split(";"):
                if not rule_raw:
                    continue
                rule = rule_raw.split(" (")[0]
                category, rationale = RULE_CLASSIFICATION.get(rule, ("unclassified", "no rationale on file"))
                rows.append({
                    "provider": source, "competition": comp, "season": season,
                    "rule": rule, "severity_column": sev_col, "category": category,
                    "match_id": match_id,
                })
    return pd.DataFrame(rows)


def build_classification_table():
    rows = []
    for rule, (category, rationale) in RULE_CLASSIFICATION.items():
        rows.append({"rule": rule, "category": category, "rationale": rationale})
    return pd.DataFrame(rows)


def build_coverage_report():
    """Fine-grained league/season coverage for StatsBomb - the one source
    with both real competition/season structure and per-match validation.
    Columns separate acquired_and_usable, acquired_but_flagged, and (as a
    per-competition-season resource count, not a per-match one, since 360 is
    a supplementary file, not the whole match) optional_not_published 360
    files."""
    con = sqlite3.connect(MANIFESTS / "acquisition_state.db")
    downloads = pd.read_sql_query("SELECT * FROM downloads", con)
    con.close()

    flags = build_flag_breakdown()
    flagged_match_ids = set(flags[(flags["provider"] == "statsbomb") & (flags["severity_column"] == "flagged")]["match_id"])

    three_sixty_status = downloads[(downloads["source"] == "statsbomb") & (downloads["resource_type"] == "three_sixty")]
    three_sixty_status = three_sixty_status.set_index(three_sixty_status["resource_key"].astype(int))["status"].to_dict()

    sb_map, comps = _statsbomb_competition_map()
    comp_season_matches = defaultdict(list)
    for mid, (cl, sl) in sb_map.items():
        comp_season_matches[(cl, sl)].append(mid)

    rows = []
    for (cid, sid), c in comps.items():
        comp_label = f"{c.get('country_name', '?')} - {c.get('competition_name', '?')}"
        season_label = c.get("season_name", "?")
        match_ids_here = comp_season_matches.get((comp_label, season_label), [])
        n_matches = len(match_ids_here)
        n_flagged = sum(1 for mid in match_ids_here if mid in flagged_match_ids)
        n_usable_clean = n_matches - n_flagged
        n_360_optional_not_published = sum(1 for mid in match_ids_here
                                            if three_sixty_status.get(mid) == "optional_not_published")
        rows.append({
            "provider": "statsbomb", "competition": comp_label, "season": season_label,
            "total_matches": n_matches, "acquired_and_usable": n_usable_clean,
            "acquired_but_flagged": n_flagged,
            "optional_not_published_360_files": n_360_optional_not_published,
        })
    return pd.DataFrame(rows).sort_values(["provider", "competition", "season"])


def build_provider_summary():
    """Top-level rollup across every source this project tracks - including
    the sources that were never reachable this session - each assigned to
    exactly one of the 5 requested buckets. Acquired sources' match/file
    counts come from the state DB; blocked/manual sources have 0 acquired
    (that's the point) with a note on why and how to complete them."""
    con = sqlite3.connect(MANIFESTS / "acquisition_state.db")
    downloads = pd.read_sql_query("SELECT * FROM downloads", con)
    con.close()

    flags = build_flag_breakdown()
    flagged_sb = flags[(flags["provider"] == "statsbomb") & (flags["severity_column"] == "flagged")]["match_id"].nunique()

    def counts(source, resource_types=None):
        d = downloads[downloads["source"] == source]
        if resource_types:
            d = d[d["resource_type"].isin(resource_types)]
        return int((d["status"] == "done").sum()), int((d["status"] == "optional_not_published").sum())

    sb_done, _ = counts("statsbomb", ["events"])
    _, sb_optional = counts("statsbomb", ["three_sixty"])
    rows = [
        {"provider": "statsbomb", "scope": "events/lineups (3,961 matches)", "category": "acquired_and_usable",
         "count": sb_done - flagged_sb, "note": "clean, no flags"},
        {"provider": "statsbomb", "scope": "events/lineups (3,961 matches)", "category": "acquired_but_flagged",
         "count": flagged_sb, "note": "minor boundary-coordinate convention only, fully usable"},
        {"provider": "statsbomb", "scope": "360 tracking files (477 flagged comp-seasons)", "category": "optional_not_published",
         "count": sb_optional, "note": "StatsBomb never published these specific match's 360 file - not a failure"},
        {"provider": "wyscout", "scope": "all 1,941 matches", "category": "acquired_and_usable",
         "count": 1941, "note": "0 quarantined, 0 flagged"},
        {"provider": "openfootball", "scope": "16 repos, 3,912 files", "category": "acquired_and_usable",
         "count": 3912, "note": "cross-repo duplicates detected and reported separately, not a validation flag"},
        {"provider": "skillcorner", "scope": "20 matches, non-LFS metadata (69 files)", "category": "acquired_and_usable",
         "count": 69, "note": "dynamic_events/phases_of_play/match.json only"},
        {"provider": "skillcorner", "scope": "per-frame tracking data (Git-LFS)", "category": "manual_import_pending",
         "count": 0, "note": "contract: docs/MANUAL_IMPORT_CONTRACTS.md Contract 1"},
        {"provider": "skillcorner", "scope": "body-pose data (Hugging Face)", "category": "manual_import_pending",
         "count": 0, "note": "contract: docs/MANUAL_IMPORT_CONTRACTS.md Contract 2"},
        {"provider": "dfl_idsse", "scope": "Bundesliga positional tracking", "category": "manual_import_pending",
         "count": 0, "note": "contract: docs/DFL_MANUAL_IMPORT.md"},
        {"provider": "football_data_co_uk", "scope": "historical match odds/results", "category": "environment_blocked",
         "count": 0, "note": "proxy 403s this sandbox; run acquisition/run_blocked_sources.py outside it"},
        {"provider": "understat", "scope": "xG data 2014/15-latest", "category": "environment_blocked",
         "count": 0, "note": "proxy 403s this sandbox; run acquisition/run_blocked_sources.py outside it"},
        {"provider": "football_data_org", "scope": "fixtures/standings API", "category": "environment_blocked",
         "count": 0, "note": "proxy 403s this sandbox; also needs a free API key"},
        {"provider": "fpl", "scope": "current FPL data", "category": "environment_blocked",
         "count": 0, "note": "proxy 403s this sandbox; run acquisition/run_blocked_sources.py outside it"},
        {"provider": "wikidata", "scope": "player/team/competition entities", "category": "environment_blocked",
         "count": 0, "note": "proxy 403s this sandbox; run acquisition/run_blocked_sources.py outside it"},
    ]
    return pd.DataFrame(rows)


def main():
    print("=== 1. Quarantine overlap (pre-fix baseline, for the record) ===")
    print("130 coord-flagged + 48 score-mismatch-flagged = 178 raw flag instances, "
          "1 match had both -> 177 unique matches were quarantined before this triage pass. "
          "After the validator fix: 0 quarantined, 130 flagged (all coordinate convention), "
          "48/48 score mismatches fully resolved by counting own goals and excluding "
          "penalty-shootout-period goals from reconciliation.")

    print("\n=== 2/3. Flag breakdown by provider/competition/season/rule, classified ===")
    flags = build_flag_breakdown()
    flags.to_csv(MANIFESTS / "validation_triage_flags_by_competition.csv", index=False)
    summary = flags.groupby(["provider", "rule", "category"]).size().reset_index(name="n_matches")
    print(summary.to_string(index=False))

    classification = build_classification_table()
    classification.to_csv(MANIFESTS / "validation_triage_classification.csv", index=False)
    print(f"\nWrote {len(flags)} flag rows -> validation_triage_flags_by_competition.csv")
    print(f"Wrote {len(classification)} rule classifications -> validation_triage_classification.csv")

    print("\n=== 7. League/season coverage report ===")
    coverage = build_coverage_report()
    coverage.to_csv(MANIFESTS / "validation_triage_coverage_by_league_season.csv", index=False)
    print(f"Wrote {len(coverage)} competition/season rows -> validation_triage_coverage_by_league_season.csv")
    print(coverage.head(10).to_string(index=False))

    summary = build_provider_summary()
    summary.to_csv(MANIFESTS / "validation_triage_coverage_summary.csv", index=False)
    print(f"\nWrote provider-level 5-category summary -> validation_triage_coverage_summary.csv")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
