"""Freezes the completed bronze snapshot: re-hashes every file recorded as
status='done' in the state DB (not trusting the stored hash blindly - a
freeze is only as trustworthy as the verification behind it), confirms it
matches what was recorded at download time, and writes a dated manifest
with a checksum summary. Read-only against bronze/ - freezing means
"this is the checkpoint", never "modify anything to make it clean".

Any mismatch is reported, not silently accepted - a snapshot with drifted
files should not be declared frozen.
"""
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from acquisition.framework import DATA, to_absolute

MANIFESTS = DATA / "manifests"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    con = sqlite3.connect(MANIFESTS / "acquisition_state.db")
    cur = con.execute(
        "SELECT source, resource_type, local_path, file_size_bytes, sha256, snapshot "
        "FROM downloads WHERE status='done'"
    )
    rows = cur.fetchall()
    con.close()

    print(f"Verifying {len(rows)} 'done' files against their recorded checksums...")

    per_source = defaultdict(lambda: {"n_files": 0, "n_bytes": 0, "hashes": []})
    mismatches = []
    missing = []
    snapshots_seen = set()

    for source, resource_type, relpath, size, recorded_sha, snapshot in rows:
        snapshots_seen.add(snapshot)
        abspath = to_absolute(relpath)
        if not abspath.exists():
            missing.append({"source": source, "resource_type": resource_type, "path": relpath})
            continue
        actual_sha = sha256_of(abspath)
        if recorded_sha and actual_sha != recorded_sha:
            mismatches.append({
                "source": source, "resource_type": resource_type, "path": relpath,
                "recorded_sha256": recorded_sha, "actual_sha256": actual_sha,
            })
            continue
        per_source[source]["n_files"] += 1
        per_source[source]["n_bytes"] += abspath.stat().st_size
        per_source[source]["hashes"].append(actual_sha)

    if mismatches:
        print(f"\n*** {len(mismatches)} FILES FAILED INTEGRITY VERIFICATION - not freezing ***")
        for m in mismatches[:20]:
            print(f"  {m['source']}/{m['resource_type']}: {m['path']}")
        (MANIFESTS / "freeze_integrity_failures.csv").write_text(
            "source,resource_type,path,recorded_sha256,actual_sha256\n" +
            "\n".join(f"{m['source']},{m['resource_type']},{m['path']},{m['recorded_sha256']},{m['actual_sha256']}"
                      for m in mismatches)
        )
        print("Details written to freeze_integrity_failures.csv. Fix or re-fetch these before re-running.")
        sys.exit(1)

    if missing:
        print(f"\nNote: {len(missing)} DB rows marked 'done' have no file on disk "
              f"(expected for quarantined-then-preserved entries; listed, not blocking):")
        for m in missing[:10]:
            print(f"  {m['source']}/{m['resource_type']}: {m['path']}")

    # A single top-level checksum over every verified file's hash, sorted for
    # determinism - lets a future check confirm the WHOLE frozen snapshot is
    # byte-identical to this moment with one comparison, without re-reading
    # every file again.
    manifest_checksum = hashlib.sha256(
        "".join(sorted(h for s in per_source.values() for h in s["hashes"])).encode()
    ).hexdigest()

    freeze_record = {
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "snapshots_included": sorted(snapshots_seen),
        "total_files_verified": sum(s["n_files"] for s in per_source.values()),
        "total_bytes_verified": sum(s["n_bytes"] for s in per_source.values()),
        "integrity_failures": len(mismatches),
        "db_rows_missing_on_disk": len(missing),
        "manifest_checksum_sha256": manifest_checksum,
        "by_source": {
            src: {"n_files": v["n_files"], "n_bytes": v["n_bytes"]}
            for src, v in sorted(per_source.items())
        },
        "note": (
            "manifest_checksum_sha256 is sha256 over the sorted, concatenated sha256 "
            "of every verified file - a single value that changes if even one byte of "
            "one file in this frozen snapshot is later altered. Per-file checksums are "
            "in download_manifest.parquet (already produced by build_reports.py)."
        ),
    }

    date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = MANIFESTS / f"bronze_snapshot_freeze_{date_tag}.json"
    out_path.write_text(json.dumps(freeze_record, indent=2))

    print(f"\n=== Bronze snapshot FROZEN ===")
    print(f"Snapshots included: {freeze_record['snapshots_included']}")
    print(f"Total files verified: {freeze_record['total_files_verified']}")
    print(f"Total bytes verified: {freeze_record['total_bytes_verified']/1e9:.2f}GB")
    print(f"Manifest checksum (whole-snapshot integrity fingerprint): {manifest_checksum}")
    print("\nBy source:")
    for src, v in sorted(per_source.items()):
        print(f"  {src}: {v['n_files']} files, {v['n_bytes']/1e9:.2f}GB")
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    main()
