# Limitations note (one page)

**Sample size is small and specific.** These 7 candidates come from 2 StatsBomb matches (2018 & 2022 World Cup Finals) and 1 SkillCorner match (Brisbane Roar 2-3 Adelaide United) plus SkillCorner's A-League season aggregates — plus 1 Wyscout match (Liverpool 4-0 Arsenal) pulled to validate the pipeline but not yet turned into a post. None of this should be read as describing a full season, a full competition, or "how a team generally plays."

**SkillCorner's richest fields here are event/phase-derived, not raw tracking.** EPV, pressure, reception-difficulty, opponents-bypassed and team-width are all real, provider-computed outputs — genuinely stronger than an event-only heuristic — but this pipeline does not hold SkillCorner's raw per-frame positions (Git-LFS-gated, unreachable in this session), so nothing here claims continuous movement, live speed traces, or pitch control.

**StatsBomb carries two distinct freeze-frame products for the same shot event** — the event's embedded `shot.freeze_frame` and the separate, standalone `three-sixty` file — and they disagree by roughly half a metre for the same real players. This pipeline now uses the standalone file as canonical (it IS the "StatsBomb 360" product; the embedded field is a different, unpublished field kept only as a disclosed reconciliation reference in `claim_audit.csv`).

**DFL/IDSSE (German tracking data) is not included.** Every host for it (Hugging Face, Figshare, Nature, the DOI resolver) is blocked by this sandboxed session's network policy — a session/environment limitation, not a licensing one. Manual-import instructions are in `docs/DFL_MANUAL_IMPORT.md` if it's needed later.

**Driblab Open Data stays disabled.** Its repository has no licence anywhere in it.

**No cross-provider player/team identity resolution was attempted.** StatsBomb, SkillCorner, and Wyscout each use their own IDs; nothing here assumes "this StatsBomb player" and "this SkillCorner player" are the same person unless they plainly are by name (and even then, not merged into one row). A proper identity layer (e.g. Reep) would be needed before combining stats on the same player across providers.

**Every "modelled" number is a model output, not a measured fact.** xG, EPV, pressure/difficulty categories, and xThreat are all provider models estimating something, not direct measurements — captions and the claim-audit file say so throughout.

**This is a proof of concept, not a production feed.** Silver/gold tables exist for exactly the data pulled for these 7 candidates, not the full StatsBomb/SkillCorner/Wyscout catalogues. Scaling up means re-running the same pipeline scripts (`pipeline/build_silver.py`, `build_silver_events.py`, `build_gold.py`) against more bronze data, not new logic.
