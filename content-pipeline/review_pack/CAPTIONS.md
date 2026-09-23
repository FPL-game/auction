# Seven finished social captions — review pack

Each caption below is ready to post as-is. Full provenance for every claim is in `claim_audit.csv`; metric definitions are in `METRIC_DEFINITIONS.md`; chart files are in `charts/`.

---

### 1. Field tilt — 2018 World Cup Final
**Chart:** `charts/01_wc2018_final_field_tilt.png`

> Croatia completed 82.5% of the final-third passing in the 2018 World Cup Final. France completed 17.5% — and won 4-2. Field tilt (final-third passing share) isn't the whole story.

*Source: StatsBomb Open Data — credit "StatsBomb" as data source (StatsBomb User Agreement).*

---

### 2. Mbappé's 2022 Final goal — StatsBomb 360
**Chart:** `charts/02_wc2022_final_mbappe_360.png`

> 0.10 xG. Per StatsBomb 360, the nearest opponent captured in the freeze-frame was 3.41m away. Mbappé's World Cup Final volley, reconstructed from real tracked positions (8 of 11 Argentina players captured in this frame).

*Source: StatsBomb Open Data, 360 (standalone three-sixty file, the canonical 360 product) — credit "StatsBomb" as data source. A different StatsBomb field (the event's embedded shot freeze-frame, not "360") gives a different value for the same instant — see `claim_audit.csv` row 2 for the full reconciliation; that value is not published.*

---

### 3. Season-long physical comparison — SkillCorner
**Chart:** `charts/03_skillcorner_season_physical_comparison.png`

> A-League full-back Dylan Pierias covered more sprint distance per 90 this season (326.8m) than Western Sydney's Brandon Borrello (281.4m) — a forward. Running data doesn't care about your position.

*Source: SkillCorner Open Data (MIT licence — credited voluntarily).*

---

### 4. Expected Possession Value — SkillCorner
**Chart:** `charts/04_skillcorner_epv_story.png`

> +0.29 Expected Possession Value in one pass — the biggest value-add of the match, per SkillCorner's own data, which flags it as leading directly to a goal. Dylan Pierias, 61'.

*Source: SkillCorner Open Data (MIT licence — credited voluntarily).*

---

### 5. Pressure / reception-difficulty — SkillCorner
**Chart:** `charts/05_skillcorner_pressure_story.png`

> SkillCorner's highest pressure category. Its hardest reception-difficulty band. Its toughest space-constraint rating. E. Alagich completed the pass anyway.

*Source: SkillCorner Open Data (MIT licence — credited voluntarily).*

---

### 6. Opponents bypassed / line-break — SkillCorner
**Chart:** `charts/07_skillcorner_bypass_pass.png` — pass vector only; SkillCorner's aggregate count is shown as text, not plotted defender positions, since this pipeline holds the count field, not raw opponent coordinates for this event.

> 10 opponents. 1 pass. SkillCorner's tracking-derived data shows P. Kikianis's ball forward in the 49th minute bypassed every outfield defender Brisbane had on the pitch.

*Source: SkillCorner Open Data (MIT licence — credited voluntarily).*

---

### 7. Team width by half — SkillCorner
**Chart:** `charts/06_skillcorner_team_shape.png`

> Brisbane Roar's average team width in possession went from 39.2m in the first half to 45.4m in the second (width data only — not a formation claim). Still lost 2-3.

*Source: SkillCorner Open Data (MIT licence — credited voluntarily). Figures are the DuckDB SQL-canonical values (404 of 423 phases with a complete width reading; 19 phases missing either a start or end value are excluded, not repaired — see `pipeline/tests/test_team_width_null_handling.py`).*
