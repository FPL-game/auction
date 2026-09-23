# Manual-import contracts

For every source this sandboxed session cannot reach or cannot fully download itself. Each contract states exactly what to supply, where, and how it gets validated once present — so supplying the files is a mechanical act, not a judgement call. DFL/IDSSE has its own, more detailed document (`docs/DFL_MANUAL_IMPORT.md`, written earlier); the entries below follow the same shape for the remaining blocked sources found during this milestone.

## Contract 1: SkillCorner raw tracking (Git-LFS)

- **What's blocked and why**: `SkillCorner/opendata`'s `*_tracking_extrapolated.jsonl` files (one per match, ~85MB each, 20 matches) are Git-LFS-tracked. This session's git proxy serves anonymous reads of public repos but explicitly does not serve LFS objects for a repo outside this project's own GitHub organisation — confirmed by a direct `git lfs pull` attempt (`batch response: access denied by the git proxy: SkillCorner/opendata is not in this session's authorized repository set`) and a follow-up `add_repo(access="push")` call, which was refused (`cross-tier adds are not supported`). This is a session/environment limit, not a licence one — SkillCorner's licence (MIT) permits it freely.
- **Target directory**: `content-pipeline/data/bronze/skillcorner/<snapshot>/tracking_raw/<match_id>/`
- **Exact filenames**: `{match_id}_tracking_extrapolated.jsonl`, one per match. The 20 match IDs are listed in `content-pipeline/data/bronze/skillcorner/<snapshot>/matches.json` (already downloaded) — e.g. `1874553_tracking_extrapolated.jsonl`.
- **How to fetch it yourself**: from a machine with normal GitHub LFS access:
  ```bash
  git clone https://github.com/SkillCorner/opendata
  cd opendata && git lfs pull --include="data/matches/*/*_tracking_extrapolated.jsonl"
  ```
- **Checksums**: none published upstream (same situation as DFL). Generate a local `sha256sum` manifest on import — integrity-only, not upstream authentication (see `docs/DFL_MANUAL_IMPORT.md` for why that distinction matters).
- **Validation on import**: each file should be valid JSON Lines (every line parses independently); frame count should be roughly `match_duration_minutes * 60 * 10` (SkillCorner tracks at 10fps per their README) ± stoppage time; cross-check a handful of frame timestamps against the match's known kickoff time from `{match_id}_match.json`.
- **Priority**: low. The event/phase-level derived data already in bronze (EPV, pressure, bypass, team width) covers most of what this project has used SkillCorner for so far; raw tracking would only matter for genuinely continuous metrics (pitch control, live speed traces) that nothing built so far has needed.

## Contract 2: SkillCorner body-pose data

- **What's blocked and why**: hosted entirely on `huggingface.co/datasets/SkillCorner/opendata-bodypose` (2 matches, ~620MB each) — `huggingface.co` is blocked by this session's network policy (see `docs/CAPABILITY_MATRIX.md` environment note). A small local sample (`data/bodypose/sample_1925299_phase406.jsonl.gz`) already exists inside the main `SkillCorner/opendata` repo and IS downloadable (not LFS, not HF) if a small worked example is ever useful without the full files.
- **Target directory**: `content-pipeline/data/bronze/skillcorner/<snapshot>/bodypose/<match_id>/`
- **Exact filenames** (per `content-pipeline/bronze/skillcorner/2026-09-23/README_upstream.md`'s manifest, already downloaded): `raw/1925299.jsonl.zip` (Brisbane Roar v Perth Glory, 2024-12-21, 623,408,231 bytes) and `raw/1996435.jsonl.zip` (Sydney FC v Adelaide United, 2025-02-01, 644,327,811 bytes).
- **Checksums**: **these ARE published upstream**, unlike every other contract in this document — `data/bodypose/MANIFEST.json` in the main repo (already in bronze) gives a `sha256` for each file. Verify against these directly; this is real upstream authentication, not just local integrity checking.
- **How to fetch it yourself**:
  ```bash
  curl -L -o 1925299.jsonl.zip https://huggingface.co/datasets/SkillCorner/opendata-bodypose/resolve/main/raw/1925299.jsonl.zip
  sha256sum 1925299.jsonl.zip   # compare to MANIFEST.json's value
  ```
- **Priority**: very low. Nothing in this project's scope has needed body-pose data; only pull this if a specific future post idea requires it.

## Contract 3: Generic template for any other blocked source

Use this shape for any source discovered later that this sandbox can't reach:

```markdown
### <Source name>
- What's blocked: <exact host(s), confirmed via a direct connection attempt — never assumed>
- Why it's legitimate: <licence, or why access is otherwise permitted>
- Target directory: content-pipeline/data/bronze/<source>/<snapshot>/
- Exact filenames/URLs: <as specific as DFL's or SkillCorner's above>
- Checksums: <published upstream, if any exist - state plainly if not>
- Validation on import: <concrete, automatable checks>
- Priority: <why it would or wouldn't matter for this project>
```

Never write "just download it" without the specifics above — the point of a contract is that supplying the files requires no judgement calls once written.
