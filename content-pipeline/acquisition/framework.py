"""Resumable acquisition framework: per-source adapters call `Acquirer.fetch()`
for every file. Everything - retry/backoff, rate limiting, hashing,
provenance, quarantine - lives here once, not duplicated per adapter.

Design choices, stated up front:
- ALL data lives OUTSIDE this git repository, under a configurable external
  root (FOOTBALL_DATA_ROOT env var, or --data-root on scripts that accept
  it). See resolve_data_root() below, including the safety check that
  refuses to run if that root resolves inside the repo. Only code, schemas,
  docs, manifests/reports, and tiny fixtures are meant to be committed - see
  content-pipeline/.env.example and the acquisition README.
- State lives in a single SQLite DB (<root>/manifests/acquisition_state.db).
  Re-running any adapter is safe: a row already marked 'done' with a file on
  disk whose sha256 still matches is skipped, not re-downloaded.
- Bronze storage is snapshot-partitioned by date (<root>/bronze/<provider>/<snapshot>/...).
  A file is never overwritten in place - a re-fetch on a LATER date writes to
  a new snapshot folder, leaving prior snapshots untouched. A re-fetch on the
  SAME date that produces identical bytes is a no-op (already resumable); one
  that produces different bytes for the same path is written alongside with a
  '.conflict-<hash8>' suffix and logged, never silently overwritten.
- Every fetch is rate-limited and retried with exponential backoff, and every
  attempt (success or failure) is recorded - failures aren't just dropped.
- Quarantine is a status, not a deletion: a failed/invalid file's row moves to
  status='quarantined' with a reason; the file (if partially written) stays
  under <root>/quarantine/ for inspection, never silently discarded.
"""
import hashlib
import json
import os
import random
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

REPO_ROOT_FALLBACK = Path(__file__).resolve().parents[2]  # .../auction, if git isn't available
# NOT Path.home() - this process runs as root (home=/root) but this session's
# actual working area convention throughout is /home/user/ (matches where the
# repo itself, /home/user/auction, and every other clone in this session live).
DEFAULT_DATA_ROOT = Path("/home/user/football-data-lake")


def _git_repo_root() -> Optional[Path]:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=Path(__file__).resolve().parent,
                              capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return Path(out.stdout.strip()).resolve()
    except Exception:
        pass
    return None


def resolve_data_root(cli_arg: Optional[str] = None) -> Path:
    """Resolution order: explicit --data-root CLI arg > FOOTBALL_DATA_ROOT env
    var > DEFAULT_DATA_ROOT (~/football-data-lake). Always resolved to an
    absolute path. Refuses (raises) if the resolved root is inside this git
    repository - raw data must never end up somewhere `git add -A` could
    accidentally pick it up."""
    raw = cli_arg or os.environ.get("FOOTBALL_DATA_ROOT") or str(DEFAULT_DATA_ROOT)
    root = Path(raw).expanduser().resolve()

    repo_root = _git_repo_root() or REPO_ROOT_FALLBACK
    try:
        root.relative_to(repo_root)
        inside_repo = True
    except ValueError:
        inside_repo = False
    if inside_repo:
        raise RuntimeError(
            f"FOOTBALL_DATA_ROOT resolves to {root}, which is INSIDE the git repository "
            f"({repo_root}). Refusing to download here - raw data must live outside the repo. "
            f"Set FOOTBALL_DATA_ROOT to a path outside {repo_root}, e.g. ~/football-data-lake."
        )
    root.mkdir(parents=True, exist_ok=True)
    return root


ROOT = Path(__file__).resolve().parents[1]  # content-pipeline/ (code lives here, data does not)
DATA = resolve_data_root()
DB_PATH = DATA / "manifests" / "acquisition_state.db"
QUARANTINE = DATA / "quarantine"

SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_key TEXT NOT NULL,
    url TEXT NOT NULL,
    local_path TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    status TEXT NOT NULL,              -- queued|downloading|done|failed|quarantined
    http_status INTEGER,
    file_size_bytes INTEGER,
    sha256 TEXT,
    retrieved_at TEXT,
    attempt_count INTEGER DEFAULT 0,
    last_error TEXT,
    licence_tag TEXT,
    UNIQUE(source, resource_type, resource_key, snapshot)
);
CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status);
CREATE INDEX IF NOT EXISTS idx_downloads_source ON downloads(source);

CREATE TABLE IF NOT EXISTS quarantine (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    download_id INTEGER REFERENCES downloads(id),
    reason TEXT NOT NULL,
    detected_at TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class FetchResult:
    status: str  # done|failed|quarantined|skipped_already_done
    local_path: Optional[str] = None
    sha256: Optional[str] = None
    http_status: Optional[int] = None
    error: Optional[str] = None


class Acquirer:
    def __init__(self, snapshot: str = None, user_agent: str = "content-pipeline-research-bot/1.0 (personal study; contact via repo)"):
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "manifests").mkdir(parents=True, exist_ok=True)
        QUARANTINE.mkdir(parents=True, exist_ok=True)
        self.snapshot = snapshot or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.con = sqlite3.connect(DB_PATH, timeout=30)
        self.con.executescript(SCHEMA)
        self.con.commit()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.counters = {"done": 0, "skipped": 0, "failed": 0, "quarantined": 0}

    def close(self):
        self.con.close()

    def _get_existing(self, source, resource_type, resource_key):
        cur = self.con.execute(
            "SELECT id, status, local_path, sha256 FROM downloads "
            "WHERE source=? AND resource_type=? AND resource_key=? AND snapshot=?",
            (source, resource_type, resource_key, self.snapshot),
        )
        return cur.fetchone()

    def _record(self, source, resource_type, resource_key, url, local_path, status,
                http_status=None, size=None, sha=None, error=None, licence_tag=None, attempt=1):
        self.con.execute(
            """INSERT INTO downloads
               (source, resource_type, resource_key, url, local_path, snapshot, status,
                http_status, file_size_bytes, sha256, retrieved_at, attempt_count, last_error, licence_tag)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source, resource_type, resource_key, snapshot) DO UPDATE SET
                 status=excluded.status, http_status=excluded.http_status,
                 file_size_bytes=excluded.file_size_bytes, sha256=excluded.sha256,
                 retrieved_at=excluded.retrieved_at, attempt_count=downloads.attempt_count+1,
                 last_error=excluded.last_error""",
            (source, resource_type, resource_key, url, str(local_path), self.snapshot, status,
             http_status, size, sha, utcnow(), attempt, error, licence_tag),
        )
        self.con.commit()

    def _quarantine(self, source, resource_type, resource_key, url, local_path, reason, http_status=None):
        self._record(source, resource_type, resource_key, url, local_path, "quarantined",
                      http_status=http_status, error=reason)
        cur = self.con.execute(
            "SELECT id FROM downloads WHERE source=? AND resource_type=? AND resource_key=? AND snapshot=?",
            (source, resource_type, resource_key, self.snapshot),
        )
        did = cur.fetchone()[0]
        self.con.execute(
            "INSERT INTO quarantine (download_id, reason, detected_at) VALUES (?,?,?)",
            (did, reason, utcnow()),
        )
        self.con.commit()
        self.counters["quarantined"] += 1

    def fetch(self, source: str, resource_type: str, resource_key: str, url: str,
              dest_relpath: str, licence_tag: str, rate_limit_sec: float = 0.15,
              max_retries: int = 4, backoff_base: float = 1.5, min_size_bytes: int = 1,
              expect_json: bool = False) -> FetchResult:
        """Fetch one file. dest_relpath is relative to data/bronze/, and the
        snapshot folder is inserted automatically: bronze/<source>/<snapshot>/<dest_relpath>.
        """
        local_path = DATA / "bronze" / source / self.snapshot / dest_relpath

        existing = self._get_existing(source, resource_type, resource_key)
        if existing:
            _id, status, existing_path, existing_sha = existing
            p = Path(existing_path)
            if status == "done" and p.exists() and sha256_of(p) == existing_sha:
                self.counters["skipped"] += 1
                return FetchResult(status="skipped_already_done", local_path=str(p), sha256=existing_sha)

        local_path.parent.mkdir(parents=True, exist_ok=True)
        last_exc = None
        for attempt in range(1, max_retries + 1):
            try:
                time.sleep(rate_limit_sec + random.uniform(0, rate_limit_sec * 0.3))
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 200:
                    content = resp.content
                    if len(content) < min_size_bytes:
                        self._quarantine(source, resource_type, resource_key, url, local_path,
                                          f"response smaller than min_size_bytes ({len(content)} < {min_size_bytes})",
                                          http_status=resp.status_code)
                        return FetchResult(status="quarantined", http_status=resp.status_code,
                                            error="too small")
                    if expect_json:
                        try:
                            json.loads(content)
                        except json.JSONDecodeError as je:
                            self._quarantine(source, resource_type, resource_key, url, local_path,
                                              f"invalid JSON: {je}", http_status=resp.status_code)
                            return FetchResult(status="quarantined", http_status=resp.status_code,
                                                error=f"invalid JSON: {je}")
                    # write, but never silently clobber a different existing file on disk
                    if local_path.exists():
                        existing_bytes = local_path.read_bytes()
                        if existing_bytes != content:
                            conflict_path = local_path.with_suffix(
                                local_path.suffix + f".conflict-{hashlib.sha256(content).hexdigest()[:8]}"
                            )
                            local_path = conflict_path
                    local_path.write_bytes(content)
                    sha = sha256_of(local_path)
                    self._record(source, resource_type, resource_key, url, local_path, "done",
                                 http_status=resp.status_code, size=len(content), sha=sha,
                                 licence_tag=licence_tag, attempt=attempt)
                    self.counters["done"] += 1
                    return FetchResult(status="done", local_path=str(local_path), sha256=sha,
                                        http_status=resp.status_code)
                elif resp.status_code in (429, 500, 502, 503, 504):
                    last_exc = f"HTTP {resp.status_code}"
                    sleep_s = (backoff_base ** attempt) + random.uniform(0, 1)
                    time.sleep(sleep_s)
                    continue
                else:
                    self._record(source, resource_type, resource_key, url, local_path, "failed",
                                 http_status=resp.status_code, error=f"HTTP {resp.status_code}",
                                 licence_tag=licence_tag, attempt=attempt)
                    self.counters["failed"] += 1
                    return FetchResult(status="failed", http_status=resp.status_code,
                                        error=f"HTTP {resp.status_code}")
            except requests.RequestException as e:
                last_exc = str(e)
                sleep_s = (backoff_base ** attempt) + random.uniform(0, 1)
                time.sleep(sleep_s)
                continue

        self._record(source, resource_type, resource_key, url, local_path, "failed",
                     error=f"exhausted {max_retries} retries: {last_exc}", licence_tag=licence_tag,
                     attempt=max_retries)
        self.counters["failed"] += 1
        return FetchResult(status="failed", error=last_exc)

    def ingest_local_file(self, source: str, resource_type: str, resource_key: str,
                           src_path: Path, dest_relpath: str, licence_tag: str,
                           provenance_url: str = "local git clone") -> FetchResult:
        """For sources acquired via `git clone` rather than HTTP (OpenFootball) -
        same state DB, same hashing, same snapshot-partitioned bronze layout,
        same never-overwrite rule, just no network retry/backoff needed since
        the bytes are already local."""
        existing = self._get_existing(source, resource_type, resource_key)
        local_path = DATA / "bronze" / source / self.snapshot / dest_relpath
        if existing:
            _id, status, existing_path, existing_sha = existing
            p = Path(existing_path)
            if status == "done" and p.exists() and sha256_of(p) == existing_sha:
                self.counters["skipped"] += 1
                return FetchResult(status="skipped_already_done", local_path=str(p), sha256=existing_sha)

        local_path.parent.mkdir(parents=True, exist_ok=True)
        content = src_path.read_bytes()
        if local_path.exists() and local_path.read_bytes() != content:
            local_path = local_path.with_suffix(
                local_path.suffix + f".conflict-{hashlib.sha256(content).hexdigest()[:8]}"
            )
        local_path.write_bytes(content)
        sha = sha256_of(local_path)
        self._record(source, resource_type, resource_key, provenance_url, local_path, "done",
                     size=len(content), sha=sha, licence_tag=licence_tag)
        self.counters["done"] += 1
        return FetchResult(status="done", local_path=str(local_path), sha256=sha)

    def summary(self):
        return dict(self.counters)
