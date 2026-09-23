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
| StatsBomb Open Data | open | Event + selective 360 | Historical, irregular updates |
| StatsBomb Commercial API | commercial | Event + 360 + pre-computed IQ stats | Near-live (hours after full time) for licensed comps |
| Driblab Open Data | **not_found** | — | — |
| Driblab PRO / API | commercial | Aggregated technical + physical + "Arrigo" metrics (no events, no coordinates) | Per-`ts` field; not documented as real-time |
| Driblab Capture | commercial (same PRO token) | Continuous tracking, delivered as a presigned link to a `.jsonl` file per processed game | Post-match file delivery, not a live stream |
| SkillCorner Open Data | open | Continuous broadcast tracking + Dynamic Events + season physical aggregates | Historical, static (10 matches) |
| SkillCorner Commercial API | commercial | Continuous tracking + physical + Game Intelligence | Per-competition delivery SLA (not publicly quantified) |
| DFL/Sportec Open Bundesliga Data | open | Continuous tracking (25 fps) + full event stream | Historical, static (7 matches) |
| ClubElo | open | Team strength rating only (no events) | Historical (1946–present) + daily update |
| football-data.co.uk | open | Match results + basic box-score + odds | Historical (Premier League since 1993/94) + weekly in-season |
| Understat | open access, **scraping caveat** | Shot-level xG (own model) | Historical + in-season, unofficial |
| FBref | open access, **degraded + scraping caveat** | Basic results/appearances only as of 20 Jan 2026 | Advanced stats (xG, xAG, progressive actions) were pulled when Stats Perform cut FBref's Opta feed; treat as no longer a viable xG/advanced-metric source |

---

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

## StatsBomb Commercial API ("commercial and Live")
- **Competitions/seasons**: whatever is in your licensed scope — not fixed, and not documented publicly.
- **Data type**: same event/360 shape as open data, plus four stats endpoints (player/team, match/season) carrying the full IQ-metrics catalogue (OBV, xGChain, xGBuildup, PPDA, PSxG, GSAA, LBP suite, pressures/counterpressures/regains, aggression) and a player-mapping endpoint reconciling StatsBomb's two internal ID systems.
- **Historical/live**: "near-live... events typically available within hours of match completion" for licensed competitions — this is StatsBomb's own documented freshness claim, not a guaranteed SLA; there is no evidence of a separately-branded "Live" product distinct from this.
- **Auth**: HTTP Basic (StatsBomb-issued credentials). **No credentials exist for this project yet — `licensed_live` mode must refuse to run against this until they do.**
- **Licence**: contractual, negotiated with StatsBomb sales — not publicly stated.
- **Confidence/limitations**: rate limits vary by licence tier (undocumented specifics); StatsBomb's own guidance is to poll `*_updated`/`last_updated` timestamps and cache rather than re-pull everything.

## Driblab Open Data — not found
No public, free Driblab product was found anywhere in football-docs' crawled guide or in a web search. Driblab's own guide (crawled 2026-09-09) states its API is "commercial and token-gated; a token comes with a Driblab PRO subscription" with no mention of a separate open tier. **Do not build against a "Driblab Open Data" source — treat this row as unconfirmed/likely non-existent** unless the user can point to a specific URL.

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
- **Competitions/seasons**: 10 matches, 2024/25 Australian A-League, released jointly by SkillCorner and PySport.
- **Data type**: broadcast (optical) continuous tracking + derived Dynamic Events for those 10 matches, plus season-level aggregated physical data.
- **Historical/live**: static historical sample, not updated on a schedule.
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

## Not used, and why
- **Impect**: has a genuinely well-defined "bypassed opponents/defenders" (packing) metric family that maps closely to the brief's "defenders bypassed" ask — but it is fully commercial with no open tier found; listed here only as the methodology reference for how a *rigorous* bypass metric should be defined (requires opponent tracking positions, not just event coordinates).
- **Wyscout**: PPDA glossary entry was useful for cross-checking the PPDA formula, but no open/free tier exists.
