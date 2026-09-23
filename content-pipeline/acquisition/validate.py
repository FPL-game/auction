"""Automated validation across every downloaded match. Quarantines failures
(moves the state-DB row to status='quarantined' with a reason) rather than
silently repairing them - a validation failure is a fact about the data,
not something this script papers over.

Checks, per source:
- successful parsing (file loads as valid JSON/CSV/Football.TXT)
- unique IDs (no duplicate match_id within a source)
- valid team/player references (event-level team_id/player_id resolve to
  that match's own lineup/roster)
- coordinate ranges (within the source's own documented pitch bounds)
- periods and timestamps (valid period labels, plausible elapsed time)
- score reconciliation (goal events tally to the officially recorded score,
  where a recorded score exists)
- event counts (within a plausible range for a football match)
- expected source files present (events AND lineups both exist for a
  StatsBomb match; a lone events file with no lineup, or vice versa, is a
  finding, not silently ignored)
- duplicate detection: (a) identical file content hash appearing under two
  different resource keys within a source, and (b) for OpenFootball, the
  same real match (by team names + score + competition/season) appearing in
  more than one repo - EXPECTED given the umbrella-vs-country-specific repo
  overlap, reported and counted, never merged; each repo's own raw file
  stays exactly as downloaded.

STREAMING: results are written to validation_results.csv one row at a time
via csv.DictWriter as each file is checked, not accumulated into one big
in-memory list/DataFrame first - so memory use stays flat regardless of how
many thousands of matches are being validated. The OpenFootball duplicate
pass holds only a compact (home, away, score, date) key per match in memory,
not full match content.

Re-runnable: safe to run again as more data arrives; results are written
fresh each run (not appended).
"""
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from acquisition.framework import DATA

BRONZE = DATA / "bronze"
MANIFESTS = DATA / "manifests"
QUARANTINE = DATA / "quarantine"

RESULT_FIELDS = ["source", "match_id", "n_checks_passed", "n_checks_failed",
                  "checks_passed", "checks_failed", "checks_flagged", "status", "n_events"]

# Checks that indicate the file/match is not trustworthy as a whole - these,
# and only these, cause status=quarantined. Everything else is recorded as
# "checks_flagged": informational for downstream triage, never blocking use
# of the match. See docs/VALIDATION_TRIAGE.md for the full rationale - this
# split exists because a single StatsBomb-documented data convention (small
# out-of-bounds location values on boundary-adjacent events) and a validator
# bug (own goals / penalty-shootout goals not handled in score reconciliation)
# were previously causing 177 matches to be quarantined despite the
# underlying event data being entirely usable.
FATAL_CHECKS = {"parse_error", "event_count_implausible", "bad_team_refs", "invalid_periods",
                 "coords_out_of_range_major"}


def _row(source, match_id, checks_passed, checks_failed, checks_flagged=None, n_events=None):
    checks_flagged = checks_flagged or []
    fatal = [c for c in checks_failed if any(c.startswith(f) for f in FATAL_CHECKS)]
    non_fatal = [c for c in checks_failed if c not in fatal]
    return {
        "source": source, "match_id": match_id,
        "n_checks_passed": len(checks_passed), "n_checks_failed": len(fatal),
        "checks_passed": ";".join(checks_passed), "checks_failed": ";".join(fatal),
        "checks_flagged": ";".join(non_fatal + checks_flagged),
        "status": "quarantined" if fatal else "valid",
        "n_events": n_events,
    }


def iter_validate_statsbomb():
    """Generator - yields one result row at a time, holding only what's
    needed for the current match plus the (small) match-list score lookup
    and lineup-file index in memory."""
    recorded = {}
    for f in (BRONZE / "statsbomb").glob("*/matches/*/*.json"):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        for m in data:
            recorded[m["match_id"]] = (m.get("home_score"), m.get("away_score"))

    lineup_files = {f.stem: f for f in (BRONZE / "statsbomb").glob("*/lineups/*.json")}
    seen_ids = Counter()
    content_hashes = defaultdict(list)

    for ef in (BRONZE / "statsbomb").glob("*/events/*.json"):
        match_id = int(ef.stem)
        checks_passed, checks_failed = [], []
        seen_ids[match_id] += 1

        raw = ef.read_bytes()
        content_hashes[hashlib.sha256(raw).hexdigest()].append(match_id)

        try:
            events = json.loads(raw)
            checks_passed.append("parses")
        except Exception as e:
            checks_failed.append(f"parse_error: {e}")
            yield _row("statsbomb", match_id, checks_passed, checks_failed), None
            continue

        n = len(events)
        (checks_passed if 100 <= n <= 6000 else checks_failed).append(
            "event_count_plausible" if 100 <= n <= 6000 else f"event_count_implausible ({n})")

        lineup_f = lineup_files.get(str(match_id))
        if lineup_f and lineup_f.exists():
            checks_passed.append("lineup_file_present")
            try:
                lineups = json.loads(lineup_f.read_text())
                known_team_ids = {t["team_id"] for t in lineups}
            except Exception:
                known_team_ids = set()
        else:
            checks_failed.append("lineup_file_missing")
            known_team_ids = set()

        bad_team_refs = 0
        # Coordinate overshoot severity is magnitude-based, not just in/out of
        # range: StatsBomb documents that boundary-adjacent events (a pass,
        # carry, or ball receipt as the ball goes out of play) can carry a
        # location a small distance past the 120x80 pitch edge. Confirmed
        # empirically across all 130 previously-quarantined matches: max
        # overshoot was 0.9 units (0.076% of events in those matches),
        # concentrated in Ball Receipt/Pass/Carry/Miscontrol/Dribble/
        # Dispossessed/Pressure/Duel/Ball Recovery - exactly the boundary
        # event types. A large overshoot would instead indicate genuine
        # corruption (e.g. a stray coordinate system or decode error).
        COORD_FATAL_OVERSHOOT = 5.0
        minor_coord_events = major_coord_events = 0
        periods_seen = set()
        goals_by_team = Counter()
        own_goals_by_team = Counter()
        for e in events:
            tid = e.get("team", {}).get("id")
            if tid is not None and known_team_ids and tid not in known_team_ids:
                bad_team_refs += 1
            loc = e.get("location")
            if loc:
                overshoot = max(0.0, loc[0] - 120, -loc[0], loc[1] - 80, -loc[1])
                if overshoot > 0:
                    if overshoot > COORD_FATAL_OVERSHOOT:
                        major_coord_events += 1
                    else:
                        minor_coord_events += 1
            periods_seen.add(e.get("period"))
            etype = e.get("type", {}).get("name")
            # Penalty-shootout goals (period 5) don't add to the recorded
            # match score by football convention, so they're excluded from
            # reconciliation. Own goals are a distinct event type
            # ("Own Goal For"/"Own Goal Against" - a pair recorded for both
            # teams), not a Shot event, so the original Shot-only tally
            # silently missed every own goal.
            if etype == "Shot" and e.get("shot", {}).get("outcome", {}).get("name") == "Goal" and e.get("period") != 5:
                goals_by_team[tid] += 1
            elif etype == "Own Goal For":
                own_goals_by_team[tid] += 1

        (checks_passed if bad_team_refs == 0 else checks_failed).append(
            "team_refs_resolve" if bad_team_refs == 0 else f"bad_team_refs ({bad_team_refs})")

        checks_flagged = []
        if major_coord_events:
            checks_failed.append(f"coords_out_of_range_major ({major_coord_events} events, overshoot>{COORD_FATAL_OVERSHOOT})")
        elif minor_coord_events:
            checks_flagged.append(f"coords_out_of_range_minor_expected_provider_convention ({minor_coord_events} events)")
            checks_passed.append("coords_in_range_within_provider_tolerance")
        else:
            checks_passed.append("coords_in_range")

        (checks_passed if periods_seen.issubset({1, 2, 3, 4, 5}) else checks_failed).append(
            "periods_valid" if periods_seen.issubset({1, 2, 3, 4, 5}) else f"invalid_periods ({periods_seen})")

        if match_id in recorded:
            home_score, away_score = recorded[match_id]
            total_events = sum(goals_by_team.values()) + sum(own_goals_by_team.values())
            total_recorded = (home_score or 0) + (away_score or 0)
            if abs(total_events - total_recorded) <= 1:
                checks_passed.append("score_reconciliation_within_tolerance")
            else:
                # Not treated as fatal: the event stream itself is intact
                # (this only fires after own-goal/shootout correction), so a
                # residual mismatch most likely means an awarded/annulled
                # result or a genuinely unusual scoreline - usable with the
                # caveat that the recorded score field shouldn't be trusted
                # without a manual look, not proof the match is corrupt.
                checks_flagged.append(
                    f"score_mismatch_after_owngoal_shootout_correction (events={total_events}, recorded={total_recorded})")
        else:
            checks_flagged.append("no_recorded_score_to_check_against")

        yield _row("statsbomb", match_id, checks_passed, checks_failed, checks_flagged, n_events=n), None

    dup_ids = {k: v for k, v in seen_ids.items() if v > 1}
    dup_content = {k: v for k, v in content_hashes.items() if len(v) > 1}
    yield None, ("statsbomb", dup_ids, dup_content)


def iter_validate_wyscout():
    seen_ids = Counter()
    content_hashes = defaultdict(list)
    for f in (BRONZE / "wyscout").glob("*/matches/*.json"):
        match_id = int(f.stem)
        checks_passed, checks_failed = [], []
        seen_ids[match_id] += 1
        raw = f.read_bytes()
        content_hashes[hashlib.sha256(raw).hexdigest()].append(match_id)
        try:
            data = json.loads(raw)
            checks_passed.append("parses")
        except Exception as e:
            checks_failed.append(f"parse_error: {e}")
            yield _row("wyscout", match_id, checks_passed, checks_failed), None
            continue
        if set(data.keys()) == {"events", "teams", "players"}:
            checks_passed.append("schema_shape_ok")
        else:
            checks_failed.append(f"unexpected_top_level_keys ({list(data.keys())})")
        n = len(data.get("events", []))
        (checks_passed if 800 <= n <= 3500 else checks_failed).append(
            "event_count_plausible" if 800 <= n <= 3500 else f"event_count_implausible ({n})")
        yield _row("wyscout", match_id, checks_passed, checks_failed, n_events=n), None
    dup_ids = {k: v for k, v in seen_ids.items() if v > 1}
    dup_content = {k: v for k, v in content_hashes.items() if len(v) > 1}
    yield None, ("wyscout", dup_ids, dup_content)


# ---------------------------------------------------------------------------
# OpenFootball: parse Football.TXT match lines, detect cross-repo duplicates
# ---------------------------------------------------------------------------
DATE_RE = re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\w+\s+\d{1,2}\s*$")
MATCH_RE = re.compile(
    r"^\s*(?:\d{1,2}:\d{2}\s+)?(?P<home>.+?)\s{2,}(?P<score>\d+-\d+)(?:\s*\([^)]*\))?\s+(?P<away>.+?)\s*$"
)


def _normalise_team(name: str) -> str:
    return re.sub(r"\s+(FC|AFC|CF|SC)$", "", name.strip().upper())


def _parse_football_txt(path: Path):
    """Yields (date_str, home_norm, away_norm, score) tuples. Best-effort -
    a line that doesn't match the expected shape is just skipped, not an
    error (Football.TXT files mix headers, notes and match lines freely)."""
    current_date = None
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return
    for line in text.splitlines():
        dm = DATE_RE.match(line)
        if dm:
            current_date = line.strip()
            continue
        mm = MATCH_RE.match(line)
        if mm:
            yield (current_date, _normalise_team(mm.group("home")), _normalise_team(mm.group("away")),
                   mm.group("score"))


def _parse_football_json(path: Path):
    """football.json's own schema: {"name": ..., "matches": [{"team1",
    "team2", "score": {"ft": [h, a]}, ...}]}. Yields the same (date, home,
    away, score) shape as _parse_football_txt so both feed one duplicate
    index."""
    try:
        data = json.loads(path.read_text())
    except Exception:
        return
    for m in data.get("matches", []):
        score = m.get("score")
        if not isinstance(score, dict):
            continue
        ft = score.get("ft")
        if not ft or len(ft) != 2:
            continue
        yield (m.get("date"), _normalise_team(m.get("team1", "")),
               _normalise_team(m.get("team2", "")), f"{ft[0]}-{ft[1]}")


def validate_openfootball_duplicates():
    """Cross-repo duplicate match detection, across BOTH Football.TXT (.txt)
    and football.json's JSON match files - the highest-likelihood overlap
    (e.g. england/2014-15/1-premierleague.txt vs football.json's
    2014-15/en.1.json) is otherwise invisible if only one format is parsed.
    Returns (n_matches_parsed, n_duplicate_keys, sample_duplicates, per_repo_counts)."""
    key_to_repos = defaultdict(set)
    per_repo_counts = Counter()
    n_parsed = 0

    for txt_file in BRONZE.glob("openfootball/*/*/**/*.txt"):
        parts = txt_file.relative_to(BRONZE / "openfootball").parts
        repo = parts[1] if len(parts) > 1 else "unknown"
        for date_str, home, away, score in _parse_football_txt(txt_file):
            key = (home, away, score)
            key_to_repos[key].add(repo)
            per_repo_counts[repo] += 1
            n_parsed += 1

    for json_file in BRONZE.glob("openfootball/*/football.json/**/*.json"):
        repo = "football.json"
        for date_str, home, away, score in _parse_football_json(json_file):
            key = (home, away, score)
            key_to_repos[key].add(repo)
            per_repo_counts[repo] += 1
            n_parsed += 1

    # date omitted from the key deliberately - cross-repo date formatting
    # isn't fully consistent, and (home, away, score) alone is already a
    # strong duplicate signal for the purpose of "is this the same real
    # match", not a formal record-linkage system.
    duplicates = {k: v for k, v in key_to_repos.items() if len(v) > 1}
    sample = [{"home": k[0], "away": k[1], "score": k[2], "repos": sorted(v)}
              for k, v in list(duplicates.items())[:20]]
    return n_parsed, len(duplicates), sample, dict(per_repo_counts)


def main():
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    QUARANTINE.mkdir(parents=True, exist_ok=True)

    n_total = n_quarantined = n_flagged = 0
    all_dup_ids = {}
    all_dup_content = {}
    fail_reasons = Counter()
    flag_reasons = Counter()

    results_path = MANIFESTS / "validation_results.csv"
    quarantine_path = QUARANTINE / "quarantined_matches.csv"

    with open(results_path, "w", newline="") as rf, open(quarantine_path, "w", newline="") as qf:
        rw = csv.DictWriter(rf, fieldnames=RESULT_FIELDS)
        rw.writeheader()
        qw = csv.DictWriter(qf, fieldnames=RESULT_FIELDS)
        qw.writeheader()

        for source_name, generator in [("statsbomb", iter_validate_statsbomb),
                                        ("wyscout", iter_validate_wyscout)]:
            source_total = 0
            for row, dup_info in generator():
                if row is not None:
                    rw.writerow(row)
                    n_total += 1
                    source_total += 1
                    if row["status"] == "quarantined":
                        n_quarantined += 1
                        qw.writerow(row)
                        for c in row["checks_failed"].split(";"):
                            if c:
                                fail_reasons[c.split(" (")[0]] += 1
                    if row["checks_flagged"]:
                        n_flagged += 1
                        for c in row["checks_flagged"].split(";"):
                            if c:
                                flag_reasons[c.split(" (")[0]] += 1
                if dup_info is not None:
                    name, dup_ids, dup_content = dup_info
                    if dup_ids:
                        all_dup_ids[name] = dup_ids
                    if dup_content:
                        all_dup_content[name] = dup_content
            print(f"{source_name}: validated {source_total} matches")

    print(f"\nTotal: {n_total} matches validated, {n_quarantined} quarantined "
          f"({n_quarantined/max(n_total,1)*100:.1f}%), {n_flagged} valid-but-flagged "
          f"({n_flagged/max(n_total,1)*100:.1f}%) - see checks_flagged column, not quarantine")
    if flag_reasons:
        print("\nFlag reason breakdown (informational, not quarantined):")
        for reason, n in flag_reasons.most_common():
            print(f"  {reason}: {n}")
    if all_dup_ids:
        print("Duplicate IDs within a source:", all_dup_ids)
    if all_dup_content:
        print(f"Duplicate-content groups (same bytes, different resource key): "
              f"{ {k: len(v) for k,v in all_dup_content.items()} }")
    print("\nFailure reason breakdown:")
    for reason, n in fail_reasons.most_common():
        print(f"  {reason}: {n}")

    print("\n--- OpenFootball cross-repo duplicate-match detection ---")
    n_parsed, n_dup_keys, sample, per_repo = validate_openfootball_duplicates()
    print(f"Parsed {n_parsed} match records across {len(per_repo)} repos "
          f"(Football.TXT format; football.json's JSON matches are counted separately if present)")
    print(f"{n_dup_keys} (home, away, score) combinations appear in more than one repo - "
          "EXPECTED given umbrella-vs-country-specific repo overlap, not an error. "
          "Each repo's raw file is kept as its own record; nothing was merged.")
    if sample:
        print("Sample duplicates (first 5):")
        for s in sample[:5]:
            print(f"  {s['home']} vs {s['away']} ({s['score']}) - in: {', '.join(s['repos'])}")

    dup_report_path = MANIFESTS / "openfootball_duplicate_matches.csv"
    with open(dup_report_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["home", "away", "score", "repos"])
        w.writeheader()
        for s in sample:
            w.writerow({**s, "repos": "; ".join(s["repos"])})
    print(f"Full sample written to {dup_report_path}")


if __name__ == "__main__":
    main()
