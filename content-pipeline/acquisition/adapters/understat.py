"""Understat adapter - EXPERIMENTAL, LOCAL-ONLY, per explicit instruction.
NOT RUNNABLE in this sandbox - understat.com is blocked by this session's
network egress policy (confirmed via direct connection attempt).

Understat has no official API or published terms permitting bulk automated
access; this adapter is built strictly for personal, local, non-redistributed
use, at a conservative rate, on publicly accessible pages only:
- no login, no paywall, no CAPTCHA-protected page is targeted
- default rate limit is 8 seconds between requests (within the 5-10s the
  instruction specified)
- every raw HTML response is cached to bronze permanently (never re-fetched
  for a completed, past match)
- if a request ever returns a CAPTCHA challenge, a 403, or repeated 429s,
  STOP - do not retry past that point, and disable this adapter. That
  detection is implemented in _check_blocked() below and raises rather than
  continuing silently.

Understat renders each page's data as JSON embedded in a <script> tag,
JS-escaped (e.g. var shotsData = JSON.parse('...\\x7B...')). This adapter
extracts that JSON rather than parsing rendered HTML tables.
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from acquisition.framework import Acquirer, DATA

BASE = "https://understat.com"
LICENCE = ("Understat - no official API/published bulk-access terms. This adapter is for personal, "
           "local, non-redistributed study only, at a conservative rate, on public pages only.")

LEAGUES = ["EPL", "La_liga", "Bundesliga", "Serie_A", "Ligue_1", "RFPL"]
SEASONS = list(range(2014, 2026))  # 2014 = the 2014/15 season, per Understat's own URL convention

JS_VAR_RE = re.compile(r"var\s+(\w+)\s*=\s*JSON\.parse\('(.+?)'\);", re.DOTALL)


class UnderstatBlockedError(RuntimeError):
    """Raised when Understat's response looks like a block/challenge page -
    the adapter must stop, not retry past this."""


def _check_blocked(html: str, status_code: int):
    if status_code in (403, 429):
        raise UnderstatBlockedError(f"HTTP {status_code} - stop, do not retry past this point")
    lowered = html.lower()
    if "captcha" in lowered or "cloudflare" in lowered and "checking your browser" in lowered:
        raise UnderstatBlockedError("response looks like a CAPTCHA/challenge page - stop")


def _extract_js_vars(html: str) -> dict:
    """Understat JS-escapes single quotes etc. inside the JSON.parse() string
    literal; decode via the same trick as most Understat scrapers: treat it
    as a JS string literal (unescape \\x hex sequences) then json.loads."""
    out = {}
    for name, raw in JS_VAR_RE.findall(html):
        decoded = raw.encode("utf-8").decode("unicode_escape").encode("latin1").decode("utf-8")
        try:
            out[name] = json.loads(decoded)
        except json.JSONDecodeError:
            out[name] = None
    return out


def fetch_league_season(acq: Acquirer, league: str, season: int, rate_limit_sec: float = 8.0):
    url = f"{BASE}/league/{league}/{season}"
    r = acq.fetch(
        source="understat", resource_type="league_season", resource_key=f"{league}_{season}",
        url=url, dest_relpath=f"league/{league}/{season}.html", licence_tag=LICENCE,
        rate_limit_sec=rate_limit_sec, min_size_bytes=1000,
    )
    if r.status == "done":
        html = (DATA / "bronze" / "understat" / acq.snapshot / f"league/{league}/{season}.html").read_text()
        _check_blocked(html, r.http_status or 200)
        js_vars = _extract_js_vars(html)
        out_path = DATA / "bronze" / "understat" / acq.snapshot / f"league/{league}/{season}_extracted.json"
        out_path.write_text(json.dumps(js_vars, indent=2))
    return r


def fetch_match(acq: Acquirer, match_id: str, rate_limit_sec: float = 8.0):
    url = f"{BASE}/match/{match_id}"
    r = acq.fetch(
        source="understat", resource_type="match", resource_key=match_id,
        url=url, dest_relpath=f"match/{match_id}.html", licence_tag=LICENCE,
        rate_limit_sec=rate_limit_sec, min_size_bytes=1000,
    )
    if r.status == "done":
        html = (DATA / "bronze" / "understat" / acq.snapshot / f"match/{match_id}.html").read_text()
        _check_blocked(html, r.http_status or 200)
        js_vars = _extract_js_vars(html)
        out_path = DATA / "bronze" / "understat" / acq.snapshot / f"match/{match_id}_extracted.json"
        out_path.write_text(json.dumps(js_vars, indent=2))
    return r


def run(acq: Acquirer, leagues: list = None, seasons: list = None):
    """League/season pages only - each league_season page's extracted
    'datesData' lists every match of that season with its Understat match
    ID, which is the resumable way to then walk to fetch_match() for each
    one (deliberately not auto-chained here - a human should review the
    league-level extraction before kicking off the much larger per-match
    fetch loop, given Understat's access terms are genuinely unclear)."""
    leagues = leagues or LEAGUES
    seasons = seasons or SEASONS
    for league in leagues:
        for season in seasons:
            try:
                fetch_league_season(acq, league, season)
            except UnderstatBlockedError as e:
                print(f"STOPPING: {e}")
                return


if __name__ == "__main__":
    print("This adapter is NOT run automatically in this sandbox - see "
          "acquisition/run_blocked_sources.py and docs/BLOCKED_SOURCE_COLLECTION.md")
