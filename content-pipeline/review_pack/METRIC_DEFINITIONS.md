# Metric-definition sheet — the 7 metrics behind this review pack

Full registry (all metrics considered for the wider project, not just these 7) is `docs/METRIC_REGISTRY.yaml`. This is the trimmed, review-facing version.

| Metric | Definition | Formula / provider field | Provider or calculated | Model version |
|---|---|---|---|---|
| **Field tilt** | Share of final-third completed passing between two teams in one match. | `team's final-third completed passes / (team's + opponent's final-third completed passes)`, final third = x>80 on StatsBomb's 0-120 pitch | locally_calculated | event-derived field tilt v1 |
| **Nearest captured opponent (360)** | Distance from a shot to the closest non-teammate position in that event's StatsBomb 360 freeze-frame. | Euclidean distance, `sqrt((x1-x2)^2+(y1-y2)^2)`, using StatsBomb's **standalone `data/three-sixty/{match}.json` file** (the canonical 360 product — anonymous, no player names). The event's separately embedded `shot.freeze_frame` field is a distinct StatsBomb product ("shot freeze-frame data") kept only as a disclosed reconciliation reference, never published as a claim. | locally_calculated (from provider-supplied positions) | n/a (direct geometry) |
| **xG (StatsBomb)** | Probability a shot results in a goal, given location/situation/defensive setup. | `statsbomb_xg` field | provider_supplied | StatsBomb xG model (version not stamped per-shot) |
| **Sprint distance per-90** | Distance covered sprinting, normalised to a 90-minute rate. | `sprint_distance_full_all / minutes_full_all * 90` | locally_calculated rate over a provider_supplied total | n/a (arithmetic only) |
| **psv99 (top speed)** | 99th-percentile sustained speed value for the season. | `psv99` field | provider_supplied | SkillCorner physical v3 |
| **Expected Possession Value (EPV) delta** | SkillCorner's estimate of how much a pass increased the team's chance of scoring soon after. | `pass_epv_delta_for` field | provider_supplied | SkillCorner's own model (internal formula not published) |
| **lead_to_goal** | Whether SkillCorner's possession-chain classification links this action to a goal. | `lead_to_goal` boolean field | provider_supplied | SkillCorner's own possession-chain logic |
| **Pressure / reception difficulty / space constraint** | Categorical ratings (easy/medium/hard/very_hard, or high/very_high pressure) SkillCorner assigns to a passer and the pass's target. | `overall_pressure_start`, `reception_difficulty_start`, `space_constraint_start` fields | provider_supplied | SkillCorner Game Intelligence model (band thresholds not published) |
| **Opponents bypassed** | Count of opposing outfield players taken out of the game by a pass, from real tracked positions. | `n_opponents_bypassed` field | provider_supplied | SkillCorner's own model (formula not published) |
| **First line break** | Whether a pass broke the opponent's first defensive line. | `first_line_break` boolean field | provider_supplied | SkillCorner's own model |
| **Team width (possession)** | How spread out a team is side-to-side while in possession, averaged per phase. | `(team_in_possession_width_start + team_in_possession_width_end) / 2`, averaged across a half's phases. **Canonical null-handling rule**: a phase is excluded entirely if either value is missing (19 of 423 phases match-wide) — not repaired from the single present value. Regression-tested (`pipeline/tests/test_team_width_null_handling.py`). | locally_calculated average over a provider_supplied per-phase field | n/a (arithmetic only) |

## Reading "provider_supplied" vs "locally_calculated"

- **provider_supplied**: the number came directly from a field StatsBomb or SkillCorner computed themselves. We did not derive it — we're citing their output.
- **locally_calculated**: this pipeline computed the number from provider-supplied *raw* fields (coordinates, totals) using a documented, versioned formula of our own. Never confuse this with "provider_supplied" in a post — the caveat/methodology columns in `claim_audit.csv` say which is which for every claim.

None of the 7 metrics above are compared *across* StatsBomb and SkillCorner as if interchangeable — e.g. StatsBomb has no EPV field and SkillCorner has no field-tilt field in this dataset; each metric here is used only against its own provider's data.
