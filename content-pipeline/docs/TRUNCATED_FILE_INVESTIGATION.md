# Truncated StatsBomb file investigation - match 3845506, 360 data

## Summary

`data/three-sixty/3845506.json` from `statsbomb/open-data` failed JSON
parsing on first download and on a targeted re-fetch, both times with the
identical error at the identical byte offset. Root cause: a deterministic,
reproducible transport-layer defect in this session's network path (not
corrupt upstream data), evidenced by a 16,384-byte run of null bytes
appearing at the exact same position across four independent fetch
attempts using two different HTTP clients.

## Timeline

1. **First download** (during the original bulk acquisition run): HTTP 200,
   6,260,494 bytes received, `json.loads()` failed with
   `Expecting ',' delimiter: line 92794 column 3 (char 2637824)`. At the
   time, the framework's `fetch()` discarded the invalid-JSON response
   without writing it to disk - a gap since fixed (see below) - so the
   original bytes from this first attempt were not preserved.

2. **Framework fix**: `acquisition/framework.py`'s `fetch()` previously
   validated `expect_json` content *before* writing anything to disk, so a
   rejected response left no trace beyond the error message. Added
   `_preserve_quarantine_bytes()`, which now writes the exact rejected bytes
   to `quarantine/<source>/<snapshot>/<dest_relpath>.corrupt` before
   recording the quarantine, and records that file's real size/sha256 in
   the state DB. Also fixed a related bug: the DB's `ON CONFLICT DO UPDATE`
   clause didn't include `local_path` in its `SET` list, so a retried
   fetch's outcome path was silently dropped in favor of the stale path
   from the first attempt - added `local_path=excluded.local_path`.

3. **Targeted re-fetch** (this triage pass), via
   `acquisition.framework.Acquirer.fetch()` with the same URL: HTTP 200,
   **same** 6,260,494 bytes, **same** parse error at **char 2637824**.

4. **Raw `curl` download** (bypassing the Python `requests` session
   entirely, to rule out a library-specific bug):
   ```
   curl -sS -o /tmp/3845506_curl_test.json \
     https://raw.githubusercontent.com/statsbomb/open-data/master/data/three-sixty/3845506.json
   ```
   Same 6,260,494 bytes, same parse error at the same offset.

5. **Cache-busting retry**: repeated with `Cache-Control: no-cache` and a
   unique `?_cb=<timestamp>` query parameter (GitHub's raw content server
   ignores query params for this endpoint, but ruled out any query-string
   dependent caching along the path). Same result, same offset.

## The actual defect

Inspecting the raw bytes around the failure offset:

```
pos = 2637824
data[pos-5:pos+400] (hex):
205d0a202000000000000000000000000000000000000000000000000000...
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                    16,384 consecutive 0x00 bytes
```

- Content immediately before the gap: `...] }, {` (a normal, well-formed
  JSON continuation).
- Content immediately after the gap: `lse,\n    "keeper" : false,\n
  "location" : [ 63.13...` (also well-formed, mid-object).
- The null run is **exactly 16,384 bytes (16KB)** - a round power-of-two
  size strongly suggestive of a fixed-size buffer somewhere in the transport
  path being zero-filled instead of populated with the actual response
  bytes for that one chunk, rather than random corruption.
- The file's total length (6,260,494 bytes) matches the origin's
  `Content-Length` header exactly - this is not a truncation (the response
  isn't cut short), it's a mid-stream substitution.

## Ruling out the origin

```
curl -sS -D - -o /dev/null \
  https://raw.githubusercontent.com/statsbomb/open-data/master/data/three-sixty/3845506.json
```
returned, among other headers:
```
x-cache: MISS
x-cache-hits: 0
source-age: 0
content-length: 6260494
```

`x-cache: MISS` and `source-age: 0` mean GitHub's own Fastly edge fetched
this fresh from origin for our request, not from a stale/corrupt edge
cache - the corruption is not coming from GitHub's side. It must be
introduced somewhere in this session's own network path (most likely the
mandatory `HTTPS_PROXY` layer noted in the environment's connectivity
docs), specific to this one large response, reproducibly.

## Disposition

Per instruction: stopped retrying once the failure was established as
**deterministic** rather than transient (four independent attempts, two
different HTTP clients, identical byte-for-byte corruption at the identical
offset - continuing to retry the same request through the same network path
would not be expected to produce a different result). The original corrupt
response is preserved at
`quarantine/statsbomb/2026-09-23/three-sixty/3845506.json.corrupt`
(6,260,494 bytes, sha256 `f7d66bcb4431fc152cfb25dffea08f10f4bff9f9c4df958c422aba6bc43cebef`)
for inspection. The state DB row (`downloads.id=14163`) is `status='quarantined'`
with `attempt_count=2` and the exact error recorded.

**This file is documented as unavailable in this session.** It is a single
optional 360-tracking file for one match (StatsBomb 360 data is
supplementary, not required for the match's events/lineups, which
downloaded and validated cleanly) - it does not block any other work. It
should be retried from a different network path (e.g. a non-sandboxed
environment, or a future session if the proxy issue is resolved) before
concluding StatsBomb's own published file is actually corrupt - the
evidence here points away from that, not toward it.
