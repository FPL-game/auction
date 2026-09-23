# DFL/IDSSE manual import instructions

**Status: adapter disabled.** Every host for this dataset (`huggingface.co`, `figshare.com`, `springernature.figshare.com`, `doi.org`, `www.nature.com`) is blocked by this project's sandboxed session's network policy — confirmed by direct connection attempts, not assumed. This is an environment limitation, not a licensing one: the data is CC-BY 4.0 and genuinely free. This doc exists so the files can be supplied from a machine that *can* reach those hosts, without the pipeline having to guess at paths or names.

## Source and licence

- Paper: Bassek, M., Rein, R., Weber, H., Memmert, D. (2025). "An integrated dataset of spatiotemporal and event data in elite soccer." *Scientific Data*, 12(1), 195. https://doi.org/10.1038/s41597-025-04505-y
- Data: https://springernature.figshare.com/articles/dataset/28196177 (mirrored at https://huggingface.co/datasets/pysport/idsse-data)
- Licence: **CC-BY 4.0**. Required attribution: name the *Deutsche Fußball Liga (DFL)* and cite the paper above.

## The 7 matches

| match_id | Competition code | Fixture |
|---|---|---|
| `J03WMX` | `DFL-COM-000001` (Bundesliga 1) | 1. FC Köln v FC Bayern München |
| `J03WN1` | `DFL-COM-000001` (Bundesliga 1) | VfL Bochum 1848 v Bayer 04 Leverkusen |
| `J03WOH` | `DFL-COM-000002` (Bundesliga 2) | Fortuna Düsseldorf v SSV Jahn Regensburg |
| `J03WOY` | `DFL-COM-000002` (Bundesliga 2) | Fortuna Düsseldorf v F.C. Hansa Rostock |
| `J03WPY` | `DFL-COM-000002` (Bundesliga 2) | Fortuna Düsseldorf v 1. FC Nürnberg |
| `J03WQQ` | `DFL-COM-000002` (Bundesliga 2) | Fortuna Düsseldorf v FC St. Pauli |
| `J03WR9` | `DFL-COM-000002` (Bundesliga 2) | Fortuna Düsseldorf v 1. FC Kaiserslautern |

(This list comes from `kloppy`'s own `kloppy/_providers/sportec.py::get_IDSSE_url`, which hardcodes it — kloppy is what actually downloads and parses these files, so its own match/competition map is the most reliable source for exact naming.)

## Exact filenames and target directory

Place files under `content-pipeline/bronze/dfl/<match_id>/`, one subfolder per match, with these exact filenames (substitute `{competition}` and `{match_id}` from the table above):

```
content-pipeline/bronze/dfl/J03WMX/
  DFL_02_01_matchinformation_DFL-COM-000001_DFL-MAT-J03WMX.xml   # metadata
  DFL_03_02_events_raw_DFL-COM-000001_DFL-MAT-J03WMX.xml          # events
  DFL_04_03_positions_raw_observed_DFL-COM-000001_DFL-MAT-J03WMX.xml  # tracking, 25fps
```
...and so on for the other 6 match_ids (5 of them use `DFL-COM-000002` in place of `DFL-COM-000001`).

Direct download URLs (from a machine with Hugging Face access), following kloppy's own template:
```
https://huggingface.co/datasets/pysport/idsse-data/resolve/main/{filename}
```

## Checksums

**Not published by the source.** Neither the Figshare record's metadata, the Hugging Face repo, nor the companion `spoho-datascience/idsse-data` GitHub repo publish per-file checksums (confirmed by inspecting the GitHub companion repo directly — it ships analysis code only, no manifest with hashes). Once files are supplied, generate and commit a `sha256sum` manifest as the durable checksum record for this project going forward:

```bash
cd content-pipeline/bronze/dfl
find . -type f -name "*.xml" -exec sha256sum {} \; > retrieval_checksums.sha256
```

Treat that self-generated manifest as the baseline for detecting future corruption or accidental modification — not as independent verification against the publisher (which isn't available).

## Validation steps to run once files are supplied

1. **File count**: exactly 21 XML files (3 per match × 7 matches). `find content-pipeline/bronze/dfl -name '*.xml' | wc -l`
2. **Per-match structural check**: each `matchinformation` XML should parse as valid XML and contain the two team names and final score matching the table above (cross-check against the well-known result, e.g. Köln v Bayern).
3. **Event count sanity**: each `events_raw` XML should contain roughly 1,500–1,800 `<Event>`-type elements (in line with a typical top-flight match's event volume) — a file with a handful of events, or tens of thousands, indicates a truncated or corrupted download.
4. **Tracking frame-rate check**: sample the first 1,000 lines of a `positions_raw_observed` file and confirm consecutive frame timestamps are ~40ms apart (25 fps), per the paper's stated capture rate.
5. **Load with kloppy** as the final check, pointed at local paths instead of the built-in URL:
   ```python
   from kloppy import sportec
   events = sportec.load_event(
       event_data="content-pipeline/bronze/dfl/J03WMX/DFL_03_02_events_raw_DFL-COM-000001_DFL-MAT-J03WMX.xml",
       meta_data="content-pipeline/bronze/dfl/J03WMX/DFL_02_01_matchinformation_DFL-COM-000001_DFL-MAT-J03WMX.xml",
   )
   ```
   A successful load (no exception, non-empty event list) is the strongest available validation, since kloppy's own deserializer enforces the expected schema.
6. Log the retrieval (source machine/date, who supplied it) in `content-pipeline/bronze/RETRIEVAL_LOG.md` alongside the other sources, so provenance stays consistent across the bronze layer.

## When to prioritise this

Per instruction, this stays disabled and does not block the rest of the pipeline. Revisit only if raw continuous-tracking analysis (team shape over time, physical/speed metrics, pitch control) becomes a priority that StatsBomb/SkillCorner/Wyscout genuinely can't support — all three of those are event-level (StatsBomb, Wyscout) or event/phase-level (SkillCorner), not raw tracking, in what this pipeline currently holds.
