# Football data capability matrix

Compiled from `football-docs` MCP (provider documentation, queried live — not from
model memory) plus targeted web searches to confirm licence terms and the
existence of products the brief asked about. Every row states what was actually
confirmed and what was not found, rather than assuming a documented API means
free/open data.

**Legend — availability tier**
- `open` — usable today with no account, or a free/self-service signup, under terms that permit this project's non-commercial social-content use.
- `commercial` — requires a paid licence; nothing in this project may claim to use it until credentials + usage rights exist.
- `not_found` — the brief named this as a product; it could not be confirmed to exist as a distinct, accessible thing.

| Source | Tier | Data shape | Historical / Live |
|---|---|---|---|
| `statsbomb_open` | open | Event data, selected historical competitions | Historical, irregular GitHub updates |
| `statsbomb_360` | open (selected matches) / commercial (rest) | Freeze-frame positions **around specific events**, not continuous tracking | Same cadence as whichever of `statsbomb_open`/`statsbomb_postmatch` it's attached to |
| `statsbomb_postmatch` | commercial | Event + pre-computed IQ stats (paid Football Data/Analysis Platform) | Post-match; exact delivery SLA is **contract-dependent, not publicly documented** — do not assume a figure |
| `statsbomb_live` | commercial | Live event/stat feed (paid Live Data/Live Analysis Platform) | Near-real-time, updating as the match happens — this is a genuinely different product from `statsbomb_postmatch`, not the same thing with a delay |
| Driblab Open Data | **exists, licence unresolved — adapter disabled** | Continuous broadcast tracking (10 fps): player/ball position, velocity, acceleration | 10 static matches (2025 season) |
| Driblab PRO / API | commercial | Aggregated technical + physical + "Arrigo" metrics (no events, no coordinates) | Per-`ts` field; not documented as real-time |
| Driblab Capture | commercial (same PRO token) | Continuous tracking, delivered as a presigned link to a `.jsonl` file per processed game | Post-match file delivery, not a live stream |
| SkillCorner Open Data | open (MIT) | Continuous broadcast tracking + Dynamic Events + season physical aggregates | Historical, static (10 matches) |
| SkillCorner Commercial API | commercial | Continuous tracking + physical + Game Intelligence | Per-competition delivery SLA (not publicly quantified) |
| DFL/Sportec Open Bundesliga Data | open (CC-BY 4.0) | Continuous tracking (25 fps) + full event stream | Historical, static (7 matches) |
| ClubElo | open | Team strength rating only (no events) | Historical (1946–present) + daily update |
| football-data.co.uk | open | Match results + basic box-score + odds | Historical (Premier League since 1993/94) + weekly in-season |
| Understat | open access, **scraping caveat** | Shot-level xG (own model) | Historical + in-season, unofficial |
| FBref | open access, **degraded + scraping caveat** | Basic results/appearances only as of 20 Jan 2026 | Advanced stats (xG, xAG, progressive actions) were pulled when Stats Perform cut FBref's Opta feed; treat as no longer a viable xG/advanced-metric source |

---

## Environment note (2026-09-23): this session's network is GitHub-only in practice
This sandboxed coding session's egress proxy allowlists GitHub (git-clone, `raw.githubusercontent.com`) and package registries, and denies almost everything else at the policy level — confirmed for `fantasy.premierleague.com`, `api.clubelo.com`, `thesportsdb.com`, `api.football-data.org`, `understat.com`, `football-data.co.uk`, `huggingface.co`, `figshare.com`, `doi.org`, and `nature.com`. This is a session-level restriction, not a per-source licensing finding, and it is why DFL/IDSSE is undownloadable here (see below) despite being genuinely free. One useful consequence: prefer GitHub-hosted mirrors of a dataset when one exists — e.g. `koenvo/wyscout-soccer-match-event-dataset` is a legitimate, CC-BY-4.0, kloppy-loadable repackage of the Pappalardo/Wyscout dataset (whose original Figshare home is blocked here), found via `withqwerty/open-football`'s curated index. Full detail in `docs/SOURCE_INVENTORY.md`.

## StatsBomb Open Data
- **Competitions/seasons**: selective — men's and women's World Cups, UEFA Euro 2020/2024, recent La Liga seasons, Ligue 1 2021/22–2022/23, Bundesliga 2023/24, Women's World Cup 2023, Women's Euro 2022, MLS 2023, plus the classic 2015/16 open set. Not a running "current season" feed — GitHub-hosted, added to irregularly.
- **Data type**: full event stream (v8 fields); 360 freeze-frame data for the competitions listed above (`competitions.json.match_available_360` marks which).
- **Historical/live**: historical only.
- **Update delay**: irregular — "new competitions added periodically," no SLA.
- **Auth**: none. `statsbombpy` wraps the GitHub repo (`github.com/hudl/open-data`) directly.
- **Licence/attribution**: StatsBomb User Agreement (github.com/hudl/open-data/blob/master/doc/LICENSE.pdf). Must credit "StatsBomb" as the source and use their logo per their Media Pack; register at statsbomb.com/resource-centre. **Non-commercial research/analysis use is the documented intent — do not assume a broader licence than this.**
- **Fields for our metrics**: shot location/body-part/technique/freeze-frame → `statsbomb_xg` (chance-quality xG, supplied); raw x/y event+carry stream → sufficient to *calculate* xT, VAEP, PPDA, field tilt, progressive passes/carries, passing networks, build-up/directness locally (see metric registry).
- **Supplied vs calculated**: `statsbomb_xg` is supplied. xGChain/xGBuildup, OBV, PSxG, GSAA, and the full IQ-metrics catalogue are **commercial-only** — open data cannot produce these; do not fabricate them from open-data fields.
- **Confidence/limitations**: high confidence in what's documented; the open xG model version isn't explicitly stamped per-match (StatsBomb reprocesses historical `statsbomb_xg` as the model improves, so re-pulling the same match later can change its value — timestamp every pull). 360 minutes must be divided by `player_season_360_minutes`, not total minutes, for any 360-derived rate stat.
- **Session note (2026-09-23): don't `git clone` the whole repo.** A full shallow clone of `statsbomb/open-data` stalled indefinitely (~20 minutes, zero bytes transferred past the initial handshake) and was abandoned. Targeted fetches of individual files via `raw.githubusercontent.com/statsbomb/open-data/master/<path>` (e.g. `data/competitions.json`, `data/events/{match_id}.json`) worked immediately and reliably — use that pattern going forward.

## StatsBomb product model (corrected)
StatsBomb is not one commercial product — it's (at least) four, and this project
must not blur them together:

- **`statsbomb_open`** — the free, selected-competition historical event data
  covered above.
- **`statsbomb_360`** — freeze-frame positions captured **around specific
  events** (shots, key passes, etc.), not a continuous frame-by-frame tracking
  stream. Free for the selected open-data matches that have it; commercial for
  everything else. Because it's event-anchored rather than continuous, it can
  support **event-level** spatial metrics (e.g. "how much space did this
  specific pass find") but never full-match shape/movement metrics like
  team compactness over 90 minutes, defensive-line height as a trend, or any
  physical/speed number — those need continuous tracking, which 360 is not.
  See "The `spatial_context` capability" below.
- **`statsbomb_postmatch`** — the paid Football Data/Analysis Platform: event
  data + the full IQ-metrics catalogue (OBV, xGChain, xGBuildup, PPDA, PSxG,
  GSAA, LBP suite, pressures/regains, aggression) delivered after the match.
  **Its exact delivery delay is contract-dependent and not documented
  publicly — this project does not assert a number for it.**
- **`statsbomb_live`** — the paid Live Data/Live Analysis Platform: a
  genuinely different, near-real-time product that updates as the match
  happens, not a delayed version of `statsbomb_postmatch`. (Earlier drafts of
  this matrix wrongly described commercial StatsBomb data as arriving "hours
  after full time" — that claim is retracted; it conflated `statsbomb_live`
  with `statsbomb_postmatch`.)

All three non-`statsbomb_open` tiers require StatsBomb credentials this
project does not have. **`licensed_live` mode must refuse to run against any
of them until real credentials and a confirmed usage licence exist.**

- **Auth**: HTTP Basic (StatsBomb-issued credentials) across all three commercial tiers.
- **Licence**: contractual, negotiated with StatsBomb sales — not publicly stated.
- **Confidence/limitations**: rate limits vary by licence tier (undocumented specifics); StatsBomb's own guidance is to poll `*_updated`/`last_updated` timestamps and cache rather than re-pull everything.

### The `spatial_context` capability
A separate availability tier from `open_demo`'s continuous-tracking sources.
It applies only to matches that have StatsBomb 360 data (open or commercial),
and it means:
- 360 gives real player/GK positions **at the moment of specific events** —
  genuinely better than plain event coordinates, and good enough for
  event-level questions ("how much space did the receiver have on this
  pass?").
- It is **not** continuous frame-by-frame tracking. There is no "the team's
  shape stayed compact for the first 20 minutes" claim available from 360 —
  that requires tracking data sampled many times a second, which 360 doesn't
  provide.
- Line-breaking passes and defenders-bypassed **may** be computable at the
  event level for 360-covered matches, using the real freeze-frame opponent
  positions — but this needs verifying directly against an actual open-data
  360 match file before any code relies on it; the metric registry flags this
  as unverified rather than assuming it works.
- Continuous movement, speed, distance, and full-match team-shape metrics
  remain unavailable from 360 under any circumstance — only the three
  continuous-tracking sources below can support those, and only for their
  small samples.

## Driblab Open Data — exists, but with no licence at all (adapter disabled)
Correction from the previous version of this matrix: this repository does
exist — [`github.com/driblab/open-data`](https://github.com/driblab/open-data),
confirmed by directly cloning it and reading every file, not by assumption.

- **Competitions/seasons**: 10 matches, 2025 season, one each from the
  Premier League, La Liga, Serie A, Bundesliga, Ligue 1, and the Champions
  League (per the README's own description — exact fixtures are inside the
  Git-LFS-tracked `.jsonl` files, not yet pulled since the licence question
  below comes first).
- **Data type**: continuous tracking "extracted from broadcast video," 10 fps,
  one `.jsonl` file per match. Per-player: position (x, y), velocity (km/h),
  acceleration (m/s²), a visibility flag. Ball: position (x, y, z), velocity,
  acceleration. Plus a camera-projection polygon per frame. This is a
  genuinely richer, more current sample than SkillCorner's or DFL's open sets
  if it turns out to be usable.
- **Licence: none found, anywhere.** The repository has no `LICENSE` file, no
  `LICENSE.md`, no licence section in the README, no citation requirement, and
  no terms-of-use or permitted/prohibited-use statement of any kind — verified
  by reading the full README (quoted below) and the repository's complete file
  listing (`.gitattributes`, `README.md`, `images/` — nothing else).

  > "Driblab is a football intelligence company specialized in data
  > collection, analytics, scouting, and decision-making tools... This
  > repository is part of that effort, providing access to match data from
  > competitions that often receive limited public coverage." — the README's
  > only statement about intent; it describes what the data is, not what
  > reuse is permitted.

  **A public GitHub repository with no licence file is not the same as an
  open licence.** GitHub's own terms are explicit that the absence of a
  licence means default copyright applies — "all rights reserved" — and
  visitors have no right to copy, modify, distribute, or build derived
  content from it beyond viewing it on GitHub, regardless of the word "open"
  in the repo's name.
- **Decision**: per the brief's own instruction, **the adapter for this
  source stays disabled and this is reported as an open uncertainty, not
  assumed permission.** Nothing in `open_demo` v1 ingests or publishes
  anything derived from this repository. If Driblab confirms a licence
  (e.g. by email, or by adding a LICENSE file), this can be revisited.
- **Confidence/limitations**: high confidence in the licence finding itself
  (a full, direct read of the repo, not a search-result summary); zero
  confidence in what the data actually contains beyond the README's
  description, since the tracking files are Git LFS pointers not yet
  resolved and won't be pulled while the licence question is open.

## Driblab PRO / API
- **Coverage**: driven by your PRO subscription's entitlement (per-competition, checked via `GET /competition/available` / `GET /season/available`); not a fixed public list.
- **Data type**: aggregated technical stats, aggregated physical stats, and "Arrigo metrics" (Driblab's own family — line-breaking/bypassing, off-ball runs, pressure) — season/match/player totals and rates. **Explicitly no event stream, no shot/pass coordinates, no cross-provider ID mapping.**
- **Historical/live**: `GET /game/{id}/ts` gives a last-updated timestamp per game; no live/streaming claim in the docs.
- **Auth**: bearer token, generated once in the PRO UI (API → Authentication). No OAuth, no refresh, one token per user.
- **Licence**: commercial; the guide "holds none of Driblab's data" and the metric definitions/data are Driblab's IP under your contract.
- **Rate limits**: 60 req/min, 60,000 req/day; breaches return HTTP 405 (not 429).
- **Fields for our metrics**: the Arrigo `line_breaking passes/carries/actions` and `out_play` (bypassed players/defenders) groups are the closest commercial match to the brief's "line-breaking passes/defenders bypassed" ask — **but the guide defines none of these metric names**, so their exact formulas are Driblab IP, not something this project can reproduce or verify independently.
- **Confidence/limitations**: **low methodology confidence** — metric names are known, definitions are not published. Known quirks: `403` can mean "route doesn't exist," not just "not entitled"; `409` is undocumented; field spellings drift between the guide and live responses (`ball_handing` vs `ball_handling`, `second_nationality` vs `secondary_nationality`) — verify against a live response, not just the guide, before trusting a field name.

## Driblab Capture
- **What it is**: the same PRO entitlement's tracking delivery — `GET /game/{id}/tracking` returns a short-lived presigned S3 link to a `.jsonl` tracking file, only for games Driblab has processed. Not a queryable tracking API and not continuous access — download promptly, the link expires.
- **Auth/licence**: identical to Driblab PRO/API above (same bearer token, same commercial terms).
- **Confidence/limitations**: coverage depends entirely on which games Driblab has chosen to process; no public list of processed games was found.

## SkillCorner Open Data
- **Competitions/seasons**: **corrected from an earlier draft of this matrix** — the repo's own `data/matches.json` currently lists **20** matches (the README text still says 10; the manifest is the source of truth), 2024/25 Australian A-League, released jointly by SkillCorner and PySport. One match (`1953632`) is mislabeled `status: "not_started"` despite having a complete file set and a real final score — verified by direct inspection; see `docs/SOURCE_INVENTORY.md`.
- **Data type**: broadcast (optical) continuous tracking + derived Dynamic Events for those 20 matches, plus season-level aggregated physical/passing/off-ball-run data. **The season aggregates cover the full 2024/25 season** (up to 29 matches per player) — broader than the 20-match tracking/event sample; don't conflate the two.
- **Historical/live**: static historical sample, not updated on a schedule.
- **Session note**: the raw per-frame tracking files (`*_tracking_extrapolated.jsonl`) are Git-LFS-tracked and could not be downloaded in this particular sandboxed session — LFS objects are only reachable for repos attached under this project's own GitHub organisation, and a cross-owner attach was explicitly refused. The per-match `dynamic_events.csv`/`phases_of_play.csv` and the season aggregates are NOT LFS-tracked and downloaded without issue.
- **Auth**: none — public GitHub repo ([`SkillCorner/opendata`](https://github.com/SkillCorner/opendata)).
- **Licence**: **MIT** — the most permissive licence in this matrix; commercial use is allowed, attribution is good practice but not a contractual MIT requirement (credit SkillCorner + PySport anyway, since we're building publishable content from it).
- **Fields for our metrics**: real player/ball tracking → genuinely supports team width/length/compactness, defensive-line height, space between lines, nearest-defender distance, pitch/space control, and (for the 10 covered matches) SkillCorner's own Dynamic Events for off-ball runs and on-ball engagements. Season-level physical aggregates cover total distance, HSR/sprint distance, and accel/decel counts for that A-League sample — **only that sample, not arbitrary players/teams.**
- **Confidence/limitations**: small, single-league, single-season sample — good for demoing tracking-derived visuals and methodology, not for making claims about specific EPL/top-5-league players or teams (no coverage there in the open set).

## SkillCorner Commercial API
- **Competitions/seasons**: per your licence.
- **Data type**: continuous tracking (v3), physical data (v3 + point releases), dynamic events (v2/v3), Game Intelligence metrics (v2) — off-ball runs, on-ball engagements, passing options, player possessions.
- **Historical/live**: match records carry `*_last_modified` fields per product for incremental sync; no publicly quantified live-delay SLA.
- **Auth**: Basic auth or `?token=` API key; official `skillcorner` Python client.
- **Licence**: commercial, per contract.
- **Data quality gate**: `physical_check_passed` boolean per row — filter to `true` for analysis-grade physical data; `dynamic_events_check` gates event-quality similarly.
- **Confidence/limitations**: well-documented OpenAPI 3.1 spec (crawled 2026-08-31); physical/speed bands are SkillCorner-specific — do not silently mix with Wyscout's or a custom pipeline's HSR/sprint thresholds.

## DFL/Sportec Open Bundesliga Data
- **Competitions/seasons**: 7 matches (2 Bundesliga, 5 Bundesliga 2), accessible via `databallpy.get_open_game()` or `kloppy.sportec.load_open_tracking_data`/`load_open_event_data`.
- **Data type**: continuous positional tracking at 25 fps + a full match-event stream (~1,600 events/match) — raw DFL XML.
- **Historical/live**: static historical sample.
- **Auth**: none.
- **Licence**: **CC-BY 4.0**, published with DFL's authorization (via figshare) — permits commercial use with attribution, which is unusually permissive for tracking data.
- **Confidence/limitations**: only 7 matches, Bundesliga only — same "great for methodology demos, not for broad current-season claims" caveat as SkillCorner Open Data.
- **Session note (2026-09-23): confirmed blocked, not a licence problem.** Every host tried — `huggingface.co` (where kloppy actually downloads from), `figshare.com`/`springernature.figshare.com` (original host), `doi.org`, `www.nature.com` — returned a policy-denial 403 from this sandboxed session's network proxy. The dataset's GitHub companion repo (`spoho-datascience/idsse-data`) was cloned successfully but contains only analysis code, not the data itself. No workaround was attempted. Exact filenames needed to supply this manually are in `docs/SOURCE_INVENTORY.md`.

## ClubElo
- **Data type**: Elo rating per club per day, no events.
- **Historical/live**: 1946–present, updated daily in-season.
- **Auth**: none. Simple CSV-over-HTTP (`api.clubelo.com/{date}` or `/{club}`).
- **Licence**: free; attribution requested, not contractually mandated in any ToS football-docs indexes.
- **Project use**: a strength prior for "upset of the week" / underdog-result outlier stories — not a fixture or result source on its own; join by a maintained team-name map.

## football-data.co.uk
- **Data type**: full-time/half-time score, shots, shots-on-target, corners, cards, and bookmaker odds. No player data, no events, no xG.
- **Historical/live**: Premier League from 1993/94; weekly CSV refresh in-season.
- **Auth**: none, direct CSV download.
- **Licence**: free for personal use; commercial use is explicitly a "ask permission" case per the site — treat this project as personal/non-commercial and say so in the README.

## Understat / FBref — flagged per the brief's own scraping rule
The brief says not to scrape FBref, WhoScored, SofaScore, "or another website" without reviewing and approving its terms. Understat falls under "another website" — no official API, access is via scraping (`soccerdata`/`understat` wrapper). **Neither is enabled in `open_demo` v1** pending that explicit review. Two things worth flagging regardless of that decision:
- **FBref's advanced stats (xG, xAG, progressive passes/carries, SCA/GCA, defensive actions) were removed site-wide on 20 January 2026** when Stats Perform cut FBref's Opta feed. FBref is no longer a viable xG source at all, contrary to older write-ups.
- Understat still appears to expose shot-level `xG`/`xGA` under its own model, but it is undocumented/unofficial and, per `soccerdata`'s own README, "fragile — any change to the scraped site breaks the package," with anti-bot protections on some sibling sites in the same package.

## Continuous-tracking samples — never generalise beyond them
Three sources give continuous (not event-anchored) tracking, and all three are
small, fixed samples, not an ongoing feed:

| Source | Matches | Frame rate | Status |
|---|---|---|---|
| SkillCorner Open Data | 20, A-League 2024/25 (manifest count; README is stale at "10") | not stated per-frame in the OpenAPI spec (broadcast tracking); raw frames not retrievable in this session (LFS-gated), event/phase-level derived data is | usable now (MIT) for event/phase-level data; raw frames blocked this session |
| DFL/Sportec Open Data | 7, Bundesliga/2 | 25 fps | usable now (CC-BY 4.0) |
| Driblab Open Data | 10, 2025 (PL/La Liga/Serie A/Bundesliga/Ligue 1/UCL) | 10 fps | **disabled — no licence** |

Every post built from any of these three must name the exact match,
competition, and season it came from, and must say plainly that the finding
is about that one match/sample — never phrased as if it describes an entire
league, a current squad, or "how [team] plays" in general. A single Bundesliga
match's pressing shape is not a Bundesliga-wide claim, and a 10-match A-League
sample from 2024/25 is not a current-season Premier League claim.

## Not used, and why
- **Impect**: has a genuinely well-defined "bypassed opponents/defenders" (packing) metric family that maps closely to the brief's "defenders bypassed" ask — but it is fully commercial with no open tier found; listed here only as the methodology reference for how a *rigorous* bypass metric should be defined (requires opponent tracking positions, not just event coordinates).
- **Wyscout**: PPDA glossary entry was useful for cross-checking the PPDA formula, but no open/free tier exists.
