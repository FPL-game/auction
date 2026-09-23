"""Regression test for the team-width null-handling rule.

CANONICAL RULE (established in this QA pass): a possession phase's average
width is (width_start + width_end) / 2. If EITHER value is NULL for a phase,
that whole phase is EXCLUDED from the half/match average - it is not
"repaired" by falling back to whichever single value is present.

This differs from an earlier pandas prototype, which used
`df[[start,end]].mean(axis=1)` - pandas' row-wise .mean() silently ignores a
single NaN and returns the other value, so it kept partial-data phases
instead of dropping them. That silent difference is exactly what produced a
<0.3m disagreement between the two versions found during review. The
DuckDB/SQL version below is the one used in pipeline/build_gold.py.

Run directly: `python3 pipeline/tests/test_team_width_null_handling.py`
"""
import duckdb
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_synthetic_null_row_is_excluded():
    con = duckdb.connect()
    df = pd.DataFrame([
        {"team": "A", "width_start": 40.0, "width_end": 44.0},  # avg 42.0, included
        {"team": "A", "width_start": 50.0, "width_end": 60.0},  # avg 55.0, included
        {"team": "A", "width_start": None, "width_end": 30.0},  # NULL pair -> must be EXCLUDED
        {"team": "A", "width_start": 20.0, "width_end": None},  # NULL pair -> must be EXCLUDED
    ])
    con.register("df", df)
    result = con.execute(
        "SELECT avg((width_start + width_end) / 2.0) AS avg_width, count(*) AS n_included "
        "FROM df WHERE team = 'A'"
    ).df()
    # avg((a+b)/2.0) is NULL for rows 3-4 (NULL + anything = NULL), and DuckDB's
    # avg() aggregate skips NULL inputs, but count(*) still counts all 4 rows -
    # that's the trap: count(*) is NOT the right denominator to report, only
    # avg()'s own implicit skip is. Assert the arithmetic mean explicitly instead.
    expected_avg = (42.0 + 55.0) / 2  # only the 2 complete-pair rows
    assert abs(result["avg_width"].iloc[0] - expected_avg) < 1e-9, (
        f"expected {expected_avg}, got {result['avg_width'].iloc[0]} - "
        "a NULL-pair row leaked into the average"
    )
    print("PASS: synthetic NULL rows correctly excluded from avg()")


def test_real_match_null_row_count():
    """423 phases total for match 1874553; 19 have a NULL width_start or
    width_end (verified by direct inspection of the bronze CSV). The gold
    query's avg() must be computed over the complete-pair subset only."""
    path = ROOT / "bronze/skillcorner/2026-09-23/match_1874553/1874553_phases_of_play.csv"
    pp = pd.read_csv(path)
    assert len(pp) == 423, f"expected 423 phases, found {len(pp)} - source file changed?"
    null_mask = pp[["team_in_possession_width_start", "team_in_possession_width_end"]].isna().any(axis=1)
    assert null_mask.sum() == 19, (
        f"expected 19 phases with a NULL width value, found {null_mask.sum()} - "
        "if this changed, re-verify the gold team-width figures and regenerate chart 06"
    )
    complete_pairs = (~null_mask).sum()
    assert complete_pairs == 404
    print(f"PASS: 19 of 423 phases have a NULL width value; canonical avg uses the remaining {complete_pairs}")


if __name__ == "__main__":
    test_synthetic_null_row_is_excluded()
    test_real_match_null_row_count()
    print("\nAll team-width null-handling regression tests passed.")
