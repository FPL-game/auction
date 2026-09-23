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


def build_disk_usage_report():
    lines = ["# Disk usage report\n"]
    total, used, free = shutil.disk_usage("/")
    lines.append(f"Filesystem: {used/1e9:.1f}GB used / {total/1e9:.1f}GB total, {free/1e9:.1f}GB free\n")
    lines.append("\n## By source (data/bronze/<source>/)\n")
    bronze = DATA / "bronze"
    if bronze.exists():
        for source_dir in sorted(bronze.iterdir()):
            if source_dir.is_dir():
                size = sum(f.stat().st_size for f in source_dir.rglob("*") if f.is_file())
                n_files = sum(1 for f in source_dir.rglob("*") if f.is_file())
                lines.append(f"- {source_dir.name}: {size/1e6:.1f}MB, {n_files} files\n")
    total_bronze = sum(f.stat().st_size for f in bronze.rglob("*") if f.is_file()) if bronze.exists() else 0
    lines.append(f"\n**Total bronze: {total_bronze/1e9:.2f}GB**\n")
    (MANIFESTS / "disk_usage_report.md").write_text("".join(lines))
    print("".join(lines))


def main():
    df = load_downloads_df()
    build_download_manifest(df)
    build_failed_downloads(df)
    build_coverage_matrix(df)
    build_disk_usage_report()


if __name__ == "__main__":
    main()
