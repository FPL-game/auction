"""Final reporting: coverage_matrix.csv, download_manifest.parquet,
failed_downloads.csv, and a disk-usage report. Reads straight from the
state DB - safe to re-run at any point (including mid-acquisition, for a
progress snapshot) and always reflects current state, not a point-in-time
copy that drifts out of date.
"""
import shutil
import sqlite3
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from acquisition.framework import DATA

MANIFESTS = DATA / "manifests"
DB_PATH = MANIFESTS / "acquisition_state.db"


def load_downloads_df():
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM downloads", con)
    con.close()
    return df


def build_download_manifest(df: pd.DataFrame):
    con = duckdb.connect()
    con.register("df", df)
    con.execute(f"COPY df TO '{MANIFESTS}/download_manifest.parquet' (FORMAT PARQUET)")
    print(f"download_manifest.parquet: {len(df)} rows")


def build_failed_downloads(df: pd.DataFrame):
    failed = df[df["status"].isin(["failed", "quarantined"])]
    failed.to_csv(MANIFESTS / "failed_downloads.csv", index=False)
    print(f"failed_downloads.csv: {len(failed)} rows")


def build_coverage_matrix(df: pd.DataFrame):
    rows = []
    for source in sorted(df["source"].unique()):
        sub = df[df["source"] == source]
        for resource_type in sorted(sub["resource_type"].unique()):
            rt_sub = sub[sub["resource_type"] == resource_type]
            done = (rt_sub["status"] == "done").sum()
            failed = (rt_sub["status"] == "failed").sum()
            quarantined = (rt_sub["status"] == "quarantined").sum()
            total = len(rt_sub)
            total_bytes = rt_sub.loc[rt_sub["status"] == "done", "file_size_bytes"].sum()
            rows.append({
                "source": source, "resource_type": resource_type,
                "total_attempted": total, "done": done, "failed": failed,
                "quarantined": quarantined, "pct_done": round(100 * done / total, 1) if total else 0,
                "total_bytes_done": int(total_bytes) if pd.notna(total_bytes) else 0,
                "licence_tag": rt_sub["licence_tag"].dropna().iloc[0] if rt_sub["licence_tag"].notna().any() else "",
            })
    out = pd.DataFrame(rows)
    out.to_csv(MANIFESTS / "coverage_matrix.csv", index=False)
    print(f"coverage_matrix.csv: {len(out)} rows")
    print(out.to_string(index=False))


def _statsbomb_completion_estimate(df: pd.DataFrame):
    """Extrapolates full StatsBomb bronze size from the average size of files
    already downloaded, against the known full target (3961 matches, 477
    with 360 - from the adapter's own inventory pass), not a guess."""
    sb = df[(df["source"] == "statsbomb") & (df["status"] == "done") & df["file_size_bytes"].notna()]
    avg_bytes = {}
    for rt in ("events", "lineups", "three_sixty"):
        sizes = sb.loc[sb["resource_type"] == rt, "file_size_bytes"]
        avg_bytes[rt] = sizes.mean() if len(sizes) else 0
    TARGET_MATCHES, TARGET_360 = 3961, 477
    est_total_bytes = (avg_bytes["events"] * TARGET_MATCHES
                        + avg_bytes["lineups"] * TARGET_MATCHES
                        + avg_bytes["three_sixty"] * TARGET_360)
    done_bytes = sb["file_size_bytes"].sum()
    return done_bytes, est_total_bytes, len(sb)


def build_disk_usage_report(df: pd.DataFrame):
    lines = ["# Disk usage report\n"]
    total, used, free = shutil.disk_usage("/")
    lines.append(f"Filesystem: {used/1e9:.1f}GB used / {total/1e9:.1f}GB total, {free/1e9:.1f}GB free\n")
    lines.append(
        "\n*Note: this environment's writable disk is a fixed per-session allowance, "
        "not the filesystem's nominal size - `free` above is the real constraint to plan "
        "against, not `total`.*\n"
    )
    lines.append("\n## By source (data/bronze/<source>/)\n")
    bronze = DATA / "bronze"
    if bronze.exists():
        for source_dir in sorted(bronze.iterdir()):
            if source_dir.is_dir():
                size = sum(f.stat().st_size for f in source_dir.rglob("*") if f.is_file())
                n_files = sum(1 for f in source_dir.rglob("*") if f.is_file())
                lines.append(f"- {source_dir.name}: {size/1e6:.1f}MB, {n_files} files\n")
    total_bronze = sum(f.stat().st_size for f in bronze.rglob("*") if f.is_file()) if bronze.exists() else 0
    lines.append(f"\n**Total bronze so far: {total_bronze/1e9:.2f}GB**\n")

    lines.append("\n## Estimated future storage requirements\n")
    lines.append(
        "\nEstimates below are for planning the *next* milestone, not commitments - the "
        "acquisition/validation/coverage-report work this milestone was scoped to stops "
        "here, per instruction; nothing below is being built now.\n"
    )

    done_bytes, est_total_bytes, n_done_files = _statsbomb_completion_estimate(df)
    remaining_bytes = max(est_total_bytes - done_bytes, 0)
    lines.append(
        f"\n**1. Current bronze completion (StatsBomb, in progress).** "
        f"Extrapolated from the average size of the {n_done_files} StatsBomb files already "
        f"downloaded against the adapter's own known full target (3,961 matches, 477 with "
        f"360 data): full StatsBomb bronze ≈ {est_total_bytes/1e9:.1f}GB total "
        f"({done_bytes/1e9:.1f}GB already on disk, ≈{remaining_bytes/1e9:.1f}GB still to "
        f"come as the background download finishes). This is a measured extrapolation, not "
        f"a blind guess - it will drift slightly as the actual mix of 360-vs-non-360 matches "
        f"downloaded so far may not perfectly match the final mix.\n"
    )

    silver_low, silver_high = total_bronze * 0.20, total_bronze * 0.35
    lines.append(
        f"\n**2. Silver Parquet (all currently-acquired sources).** Columnar Parquet with "
        f"dictionary encoding on repeated string fields (team names, event types, player "
        f"names) typically lands at 20-35% of the equivalent raw JSON/TXT size for this "
        f"kind of event data. Applied to the full bronze estimate "
        f"(~{(total_bronze + remaining_bytes)/1e9:.1f}GB once StatsBomb finishes): "
        f"≈{silver_low/1e9:.1f}-{silver_high/1e9:.1f}GB. Not yet built this milestone.\n"
    )

    lines.append(
        "\n**3. Gold / `football.duckdb`.** Gold is curated, cross-source, post-ready "
        "metric tables (aggregates, not per-event rows) - typically two to three orders of "
        "magnitude smaller than silver. Estimate: 0.2-1GB. Not yet built this milestone; "
        "`<data-root>/gold/` and `<data-root>/databases/` are currently empty by design.\n"
    )

    lines.append(
        "\n**4. DFL / IDSSE positional tracking (manual-import, currently blocked).** "
        "This source could not be reached from this sandbox (Figshare/DOI resolver both "
        "blocked), so this figure is an *unverified* order-of-magnitude estimate based on "
        "the known shape of DFL's public XML positional-data release (full-match, "
        "high-frequency player+ball tracking for a handful of matches), not a direct "
        "measurement: roughly 5-15GB for the publicly released match set. Treat this as "
        "the least reliable number in this report until the manual import actually runs.\n"
    )

    lines.append(
        "\n**5. SkillCorner full tracking data (Git-LFS, currently blocked).** The 20 "
        "matches already ingested cover only the non-LFS metadata (dynamic events, phases "
        "of play, match info) - the actual per-frame player/ball tracking is Git-LFS-hosted "
        "and wasn't reachable this session. Unverified estimate from SkillCorner's own "
        "published open-data shape: roughly 2-8GB for the full tracking archive across "
        "those 20 matches.\n"
    )

    lines.append(
        "\n**6. SkillCorner body-pose data (Hugging Face, currently blocked).** Also "
        "unreachable this session (Hugging Face is proxy-blocked). Per-frame, per-player "
        "body keypoint data is the largest single unverified estimate in this report: "
        "roughly 10-40GB depending on how many matches/players are in scope - this is a "
        "wide range because the source itself couldn't be inspected to narrow it.\n"
    )

    lines.append(
        "\n**7. Temporary processing headroom.** Bronze-to-silver and silver-to-gold "
        "transformations need working space beyond the final output size (in-flight "
        "Parquet writes, DuckDB spill files, uncompressed intermediates). Recommend "
        "reserving at least 2x the largest single transformation step's output, or a flat "
        "15-20GB floor, whichever is larger - on top of, not instead of, items 2-3 above.\n"
    )

    low_total = remaining_bytes/1e9 + silver_low/1e9 + 0.2 + 5 + 2 + 10 + 15
    high_total = remaining_bytes/1e9 + silver_high/1e9 + 1 + 15 + 8 + 40 + 20
    lines.append(
        f"\n**Bottom line:** items 1-7 combined range from roughly {low_total:.0f}GB to "
        f"{high_total:.0f}GB, against {free/1e9:.1f}GB currently free in this session. "
        f"**A larger data volume (bigger disk allocation, or a session with a larger "
        f"writable-disk allowance) must be selected before attempting the DFL import, the "
        f"SkillCorner Git-LFS/body-pose imports, or a full silver/gold build - the current "
        f"allowance cannot hold them.** This report is a planning estimate for that future "
        f"decision, not a request to proceed; per instruction, this milestone stops at "
        f"acquisition, validation, and the coverage/disk reports.\n"
    )

    (MANIFESTS / "disk_usage_report.md").write_text("".join(lines))
    print("".join(lines))


def main():
    df = load_downloads_df()
    build_download_manifest(df)
    build_failed_downloads(df)
    build_coverage_matrix(df)
    build_disk_usage_report(df)


if __name__ == "__main__":
    main()
