# content-pipeline — implementation plan and data-access audit

Status: **planning only**. No acquisition code has been written. Per the
brief: acquisition code starts only after a permitted source is identified
and the first version's historical-vs-live status is settled — both are
resolved below.

See also: [`docs/CAPABILITY_MATRIX.md`](docs/CAPABILITY_MATRIX.md) (per-source
audit) and [`docs/METRIC_REGISTRY.yaml`](docs/METRIC_REGISTRY.yaml) (per-metric
definitions, formulas, and tiers). This document is the plan that ties them
together; it doesn't restate their contents.

## Data-access audit — conclusion

**At least one permitted source is confirmed**: StatsBomb Open Data (event +
selective 360, CC-license-equivalent StatsBomb User Agreement, attribution
required, no auth) — cross-checked against `football-docs` and its own
GitHub repo, not assumed from memory. Two more open, well-licensed sources
extend it:

- **SkillCorner Open Data** (MIT licence, 10 matches, 2024/25 A-League,
  continuous tracking) — for tracking-derived metrics and their visuals.
- **DFL/Sportec Open Bundesliga Data** (CC-BY 4.0, 7 matches, tracking + full
  events) — a second, differently-licensed tracking source, useful for
  cross-checking the tracking pipeline against StatsBomb's event pipeline
  independently.
- **ClubElo** and **football-data.co.uk** as lightweight, no-auth context
  sources (team-strength prior, historical results/odds) for framing stories,
  not for advanced metrics.

**Historical or live, for v1: historical.** Every one of the above is a
static or irregularly-updated open dataset — none is a live feed. `open_demo`
mode is therefore the only mode that can run today. `licensed_live` is built
as an interface with no working implementation, exactly as the brief
specifies — it must fail loudly and specifically ("no credentials configured
for provider X") rather than silently falling back to demo data or pretending
to work.

**Explicitly not usable for v1, and why:**
- Driblab Open Data — could not confirm this product exists (see capability matrix). Not built against.
- Driblab PRO/API, Driblab Capture, SkillCorner Commercial API, StatsBomb Commercial API — all commercial; interfaces only, gated behind credentials that don't exist yet.
- Understat, FBref (advanced stats) — gated behind the brief's own scraping-review rule; FBref's advanced stats no longer exist to scrape as of 20 Jan 2026 regardless.

## Two operating modes

### `open_demo`
Runs end-to-end today, against the sources above. Produces historical/evergreen
content: "on this day," record/streak stories, methodology demos of
tracking-derived visuals using the two small open tracking samples. Every
output row's `source` and `source_timestamp` point at one of the confirmed
open sources; every metric used is tagged `availability_tier: open_demo` (or
`open_demo, sample only`) in the metric registry.

### `licensed_live`
Ships as real interfaces — a `Provider` abstract base per commercial source
(StatsBomb commercial, Driblab PRO, SkillCorner commercial) with the method
signatures the calculation layer expects — but every concrete implementation
raises a explicit, named error (`CredentialsNotConfigured` /
`LicenceNotConfirmed`) until:
1. Real credentials are present (env var / secrets, never committed), **and**
2. A human has confirmed in writing (a config flag, not an inferred default)
   that a usage licence covering this project's intended use (public social
   posts) is actually in place — a subscription that only covers "internal
   analysis" is not the same licence as one that covers publishing derived
   stats externally, and this project must not assume they're the same.

`licensed_live` mode is not "the same code with a flag flipped" — the
`ProviderRegistry` refuses to route any metric tagged `availability_tier:
licensed_live` in the metric registry to anything but a provider that has
passed both checks above. This is enforced in code, not left to a docstring.

## Architecture

```
content-pipeline/
  docs/
    CAPABILITY_MATRIX.md        (done)
    METRIC_REGISTRY.yaml        (done)
  config/
    sources.yaml                 # per-source: mode, auth requirement, licence note, base URL
    metrics.yaml -> generated from docs/METRIC_REGISTRY.yaml at load time, not hand-duplicated
  ingest/
    statsbomb_open.py            # open_demo
    skillcorner_open.py          # open_demo
    dfl_open.py                  # open_demo
    clubelo.py                   # open_demo, context only
    football_data_co_uk.py       # open_demo, context only
    statsbomb_commercial.py      # licensed_live interface, no working impl
    driblab_pro.py                # licensed_live interface, no working impl
    skillcorner_commercial.py    # licensed_live interface, no working impl
  clean/
    teams.py players.py matches.py events.py tracking.py   # standardised tables, per output spec below
  compute/
    spadl.py                     # StatsBomb events -> SPADL (socceraction)
    xt.py vaep.py                 # locally-trained models, versioned per metric registry
    event_derived.py              # PPDA, field tilt, progressive passes/carries, buildup, directness, SCA
    tracking_derived.py           # team shape, pitch control, physical (SkillCorner/DFL sample only)
    percentiles.py                 # cohort-aware percentile profiles
  posts/
    candidate_builder.py          # calculation-table row -> post_candidates.csv row, template-only text
    charts.py                     # the 3-5 reusable chart functions -> PNG/SVG + chart-ready JSON/CSV
  tests/
    test_known_matches.py         # fixed matches with hand-checked expected values (see Testing below)
  README.md
  run.py                          # single orchestrator entrypoint, --mode open_demo|licensed_live
```

Nothing under `ingest/*_commercial.py` / `*_pro.py` is called by `run.py`'s
`open_demo` path. `licensed_live` is a separate explicit invocation, and it
fails fast if the two checks above aren't met — it does not "try the API and
catch the error," it checks configuration before making any request.

## Methodology rules, as enforced design constraints

Each rule from the brief maps to a specific place in the code, not just a
comment:

- **Heuristic vs true line-breaking/bypass metrics** → `line_breaking_passes`
  and `defenders_bypassed` are tagged `not_computable`/`licensed_live` in the
  registry, and `compute/event_derived.py` contains no function with those
  names — only StatsBomb 360 (commercial) or Impect (commercial, unlicensed)
  can produce them. Anything superficially similar computed from plain event
  data must use a different, honestly-named metric_id.
- **No physical distance/speed from event data** → `compute/event_derived.py`
  imports nothing from `compute/tracking_derived.py` and vice versa; physical
  metrics only exist where `required_fields` includes continuous tracking
  positions, per the registry.
- **Version every xG/xT/VAEP/possession-value model** → `model_version` is a
  required, non-null field on every calculation-table row; `compute/xt.py`
  and `compute/vaep.py` refuse to run without a `model_version` string
  supplied by the caller (grid size + training scope for xT; feature set +
  training scope for VAEP).
- **Explicit progression thresholds / coordinate normalisation** → every
  event-derived metric function takes its threshold/convention as an
  explicit parameter with no silent default; the chosen value is written
  into that row's `model_version` or `caveats` field, not just into code
  comments.
- **Percentile cohort disclosure** → `compute/percentiles.py`'s output type
  is a struct that cannot be constructed without `league`, `season`,
  `position_group`, `min_minutes`, and `cohort_size` — there is no code path
  that produces a percentile number without them attached.
- **Provider-supplied vs locally-calculated** → every calculation-table row
  carries a `computation_type` field (`provider_field` | `locally_calculated`
  | `sample_only`), populated straight from each metric's registry entry.
- **Live numbers wait for completion** → any `licensed_live` ingestion (once
  credentials exist) must check the source's own finality signal (e.g.
  StatsBomb's `data_checked` where available) before a row is marked
  `final`; not-yet-final rows are tagged `provisional` and `post_candidates.csv`
  excludes provisional rows by default (opt-in flag to include them, clearly
  watermarked).
- **Modelled stats as estimates** → any row whose `computation_type` is
  `locally_calculated` or whose source is itself a model (xG, xT, VAEP,
  OBV, GSAA, gk_positioning_error) gets a caveat sentence auto-appended in
  `posts/candidate_builder.py` — "this is a modelled estimate, not a
  measured fact" — that the template layer cannot omit.

## Output spec

- **Cleaned tables** (`clean/`): `matches`, `teams`, `players`, `events`,
  `tracking_frames` — one canonical schema regardless of source, with a
  `source` + `source_id` column on every row so any value can be traced back.
- **Calculation table**: one row per (metric_id, entity, match/season scope,
  computed_at) — this is what `compute/*` writes and what `posts/*` reads;
  reproducible means re-running the pipeline against the same cached raw data
  reproduces the same calculation table byte-for-byte (or documents why not,
  e.g. a re-trained model).
- **`post_candidates.csv`** — columns exactly as specified in the brief:
  `hook, verified_statistic, plain_english_explanation, team_player_match,
  comparison_or_baseline, source_url, source_timestamp, methodology,
  confidence, caveat, recommended_platform, chart_type, suggested_post_copy`.
  Every value traces to one calculation-table row; `candidate_builder.py`
  has no free-text field that isn't built from a template + that row's own
  values.
- **Source and methodology metadata**: a manifest per pipeline run
  (`run_manifest.json`) — which sources were hit, at what time, which metric
  registry version, which model versions.
- **Chart-ready JSON/CSV**: the exact data slice each chart was built from,
  saved alongside the PNG/SVG — so a chart's numbers are independently
  checkable against the calculation table.
- **Reusable SVG/PNG visualisations**: the chart functions in `posts/charts.py`
  matching the metric registry's `recommended_visual` field — implemented
  with `mplsoccer` (pitch-native charts) since it's already indexed in
  football-docs and is the standard for this exact job.
- **Tests using known matches**: fix 2-3 StatsBomb Open Data matches (e.g. a
  World Cup final with well-known, citable stats) and 1 SkillCorner Open Data
  / DFL Open Data match, hand-verify a handful of expected values (final
  score, a specific player's xG, a specific team-shape number) once, and
  assert the pipeline reproduces them — this is what makes "reproducible"
  checkable rather than asserted.
- **README**: setup (Python version, `requirements.txt`), how to run each
  mode, exactly which licences apply to which output (StatsBomb attribution
  requirement, SkillCorner/DFL MIT/CC-BY notices), and the explicit
  limitations list from the capability matrix (small tracking samples, no
  current top-5-league tracking coverage, no true line-breaking/bypass
  metrics without a commercial licence).

## Publishing

Nothing in `run.py` posts anywhere. `post_candidates.csv` is the terminal
output of the pipeline; getting it in front of an actual social account is a
separate, human-gated step by design, per the brief's "do not publish
anything automatically."

## Next step

This plan, the capability matrix, and the metric registry are the requested
first deliverable. I have not scaffolded `ingest/`, `clean/`, `compute/`, or
`posts/` yet, and won't start writing acquisition code until you confirm the
source selection above (StatsBomb Open Data + SkillCorner Open Data + DFL
Open Data, `open_demo`-only for v1) is what you want built first.
