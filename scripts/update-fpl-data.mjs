// Runs on a schedule via .github/workflows/update-fpl-data.yml (GitHub-hosted
// runners can reach the public FPL API; this repo's dev/build sandboxes cannot).
//
// Pulls the official FPL API and refreshes src/data/auctionLeague.json:
//  - full player pool + season points (cross-referenced against drafted rosters)
//  - which gameweek is live right now
//  - live, in-progress scores for that gameweek (from roster player points)
//  - finalized match results + standings once a gameweek completes
//
// Never touches teams/rosters/budgets/fixtures — those are edited by hand
// (draft results, transfers) as the season happens.
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { POSITION_BY_ELEMENT_TYPE } from "../src/lib/auctionLeagueUtils.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_PATH = path.join(__dirname, "..", "src", "data", "auctionLeague.json");
const API_BASE = "https://fantasy.premierleague.com/api";
const FETCH_HEADERS = { "User-Agent": "auction-league-bot/1.0 (+https://nikhildeshpande.com)" };

async function fetchJson(url) {
  const res = await fetch(url, { headers: FETCH_HEADERS });
  if (!res.ok) throw new Error(`${url} -> HTTP ${res.status}`);
  return res.json();
}

function gwScoreForRoster(roster, liveById) {
  let score = 0;
  let matched = 0;
  for (const p of roster) {
    if (p.playerId != null && liveById.has(p.playerId)) {
      score += liveById.get(p.playerId).stats.total_points;
      matched++;
    }
  }
  return { score, matched, total: roster.length };
}

async function main() {
  const state = JSON.parse(await readFile(DATA_PATH, "utf8"));

  const bootstrap = await fetchJson(`${API_BASE}/bootstrap-static/`);
  const clubById = new Map(bootstrap.teams.map((t) => [t.id, t.name]));

  // ---- Refresh the player pool (points + drafted status), keep manual playerId links ----
  // selectedByPercent and expectedPoints (FPL's own next-gameweek projection) let the
  // Unpicked Players page default-sort by "likely to matter" rather than raw season
  // points, which is near-meaningless in the first few gameweeks of a season.
  const existingByName = new Map(state.players.map((p) => [p.name, p]));
  state.players = bootstrap.elements.map((el) => {
    const name = `${el.first_name} ${el.second_name}`;
    const prior = existingByName.get(name);
    return {
      id: el.id,
      name,
      pos: POSITION_BY_ELEMENT_TYPE[el.element_type] || "?",
      club: clubById.get(el.team) || "?",
      pts: el.total_points,
      selectedByPercent: parseFloat(el.selected_by_percent) || 0,
      expectedPoints: parseFloat(el.ep_next) || 0,
      nowCost: el.now_cost / 10,
      draftedBy: prior?.draftedBy ?? null,
    };
  });

  // ---- Work out which gameweek is current / live ----
  const events = bootstrap.events;
  const current = events.find((e) => e.is_current) || null;
  const mostRecentFinished = [...events].reverse().find((e) => e.finished) || null;
  const next = events.find((e) => e.is_next) || null;
  const liveEvent = current || null;

  state.meta.lastFplSync = new Date().toISOString();
  state.meta.currentGameweek = liveEvent?.id ?? next?.id ?? mostRecentFinished?.id ?? null;

  const rostersInPlay = state.teams.some((t) => t.roster.length > 0);
  state.meta.seasonStatus = rostersInPlay ? "in-season" : "pre-draft";

  if (!rostersInPlay) {
    state.liveScores = null;
    await writeFile(DATA_PATH, JSON.stringify(state, null, 2) + "\n");
    console.log("No rosters drafted yet — refreshed player pool only.");
    return;
  }

  // ---- Live, in-progress scores for the current gameweek ----
  if (liveEvent && !liveEvent.finished) {
    const live = await fetchJson(`${API_BASE}/event/${liveEvent.id}/live/`);
    const liveById = new Map(live.elements.map((e) => [e.id, e]));
    const gwFixture = state.fixtures.find((f) => f.gw === liveEvent.id);
    state.liveScores = {
      gw: liveEvent.id,
      finished: false,
      matches: (gwFixture?.matches || []).map(([a, b]) => {
        const teamA = state.teams.find((t) => t.id === a);
        const teamB = state.teams.find((t) => t.id === b);
        const sa = gwScoreForRoster(teamA.roster, liveById);
        const sb = gwScoreForRoster(teamB.roster, liveById);
        return { a, b, scoreA: sa.score, scoreB: sb.score };
      }),
    };
  } else {
    state.liveScores = null;
  }

  // ---- Finalize results for any completed gameweek not yet recorded ----
  const finishedEvents = events.filter((e) => e.finished);
  for (const ev of finishedEvents) {
    const gwFixture = state.fixtures.find((f) => f.gw === ev.id);
    if (!gwFixture) continue;
    const alreadyDone = gwFixture.matches.every(
      ([a, b]) => state.results[`${ev.id}-${a}-${b}`],
    );
    if (alreadyDone) continue;

    const live = await fetchJson(`${API_BASE}/event/${ev.id}/live/`);
    const liveById = new Map(live.elements.map((e) => [e.id, e]));
    for (const [a, b] of gwFixture.matches) {
      const teamA = state.teams.find((t) => t.id === a);
      const teamB = state.teams.find((t) => t.id === b);
      const sa = gwScoreForRoster(teamA.roster, liveById);
      const sb = gwScoreForRoster(teamB.roster, liveById);
      state.results[`${ev.id}-${a}-${b}`] = { scoreA: sa.score, scoreB: sb.score };
    }
  }

  state.meta.lastUpdated = new Date().toISOString();
  await writeFile(DATA_PATH, JSON.stringify(state, null, 2) + "\n");
  console.log(`Synced FPL data. Current GW: ${state.meta.currentGameweek ?? "n/a"}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
