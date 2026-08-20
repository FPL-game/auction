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

const FIRESTORE_PROJECT = "fpl-auction";
const FIRESTORE_BASE = `https://firestore.googleapis.com/v1/projects/${FIRESTORE_PROJECT}/databases/(default)/documents`;

async function fetchJson(url) {
  const res = await fetch(url, { headers: FETCH_HEADERS });
  if (!res.ok) throw new Error(`${url} -> HTTP ${res.status}`);
  return res.json();
}

// ---- Firestore REST value decoding (read-only; teams/draftLog rules allow public read) ----
function decodeFirestoreValue(v) {
  if (v.stringValue !== undefined) return v.stringValue;
  if (v.integerValue !== undefined) return Number(v.integerValue);
  if (v.doubleValue !== undefined) return v.doubleValue;
  if (v.booleanValue !== undefined) return v.booleanValue;
  if (v.arrayValue) return (v.arrayValue.values || []).map((x) => decodeFirestoreValue(x));
  if (v.mapValue) return decodeFirestoreMap(v.mapValue);
  if (v.timestampValue !== undefined) return v.timestampValue;
  return null;
}

function decodeFirestoreMap(m) {
  const out = {};
  for (const [k, v] of Object.entries(m.fields || {})) out[k] = decodeFirestoreValue(v);
  return out;
}

// Live drafted rosters/budgets actually live in Firestore (the admin panel writes there
// directly for instant updates) — this static JSON's `teams` array is otherwise never
// touched after the initial seed, so it's synced here on every run to stay accurate for
// anything computed at build time (Live Scores, Match Recaps, rumour generation).
async function fetchLiveTeams() {
  const res = await fetch(`${FIRESTORE_BASE}/teams`);
  if (!res.ok) throw new Error(`Firestore teams fetch -> HTTP ${res.status}`);
  const body = await res.json();
  const byId = {};
  for (const doc of body.documents || []) {
    const id = Number(doc.name.split("/").pop());
    byId[id] = decodeFirestoreMap(doc);
  }
  return byId;
}

// Recent add/release moves, for fan-reaction posts in the Social Media feed.
async function fetchRecentDraftLog() {
  const res = await fetch(`${FIRESTORE_BASE}/draftLog`);
  if (!res.ok) return [];
  const body = await res.json();
  return (body.documents || [])
    .map((doc) => decodeFirestoreMap(doc))
    .filter((d) => d.type === "add")
    .slice(-10);
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

  const [bootstrap, liveTeamsById, recentMoves] = await Promise.all([
    fetchJson(`${API_BASE}/bootstrap-static/`),
    fetchLiveTeams(),
    fetchRecentDraftLog(),
  ]);
  const clubById = new Map(bootstrap.teams.map((t) => [t.id, t.name]));

  // ---- Sync live rosters/budgets from Firestore into the static teams array ----
  // The admin panel writes drafted rosters straight to Firestore for instant updates;
  // this keeps the build-time JSON (Live Scores, Match Recaps, rumours) in step with it.
  for (const team of state.teams) {
    const live = liveTeamsById[team.id];
    if (live) {
      team.remainingBudget = live.remainingBudget ?? team.remainingBudget;
      team.waiverBudget = live.waiverBudget ?? team.waiverBudget;
      team.roster = live.roster ?? team.roster;
    }
  }

  const draftedIdToTeamId = new Map();
  for (const team of state.teams) {
    for (const p of team.roster) {
      if (p.playerId != null) draftedIdToTeamId.set(p.playerId, team.id);
    }
  }

  // ---- Refresh the player pool (points + drafted status) ----
  // selectedByPercent and expectedPoints (FPL's own next-gameweek projection) let the
  // Unpicked Players page default-sort by "likely to matter" rather than raw season
  // points, which is near-meaningless in the first few gameweeks of a season.
  state.players = bootstrap.elements.map((el) => {
    const name = `${el.first_name} ${el.second_name}`;
    return {
      id: el.id,
      name,
      pos: POSITION_BY_ELEMENT_TYPE[el.element_type] || "?",
      club: clubById.get(el.team) || "?",
      pts: el.total_points,
      eventPoints: el.event_points ?? 0,
      selectedByPercent: parseFloat(el.selected_by_percent) || 0,
      expectedPoints: parseFloat(el.ep_next) || 0,
      nowCost: el.now_cost / 10,
      news: el.news || "",
      newsAdded: el.news_added || null,
      chanceOfPlaying: el.chance_of_playing_next_round,
      draftedBy: draftedIdToTeamId.get(el.id) ?? null,
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

  state.rumours = generateRumours(state, recentMoves);

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

// ---- Social Media feed: fictional-persona flavor text over 100% real, current data ----
// (unpicked players, team budgets, actual rosters, real recent moves, real results once
// they exist) — regenerated fresh on every sync run so the feed genuinely changes over
// time with zero manual input, same as the other News Wire sections. Two persona pools —
// "insider" accounts for analysis-flavored posts, "fan" accounts for banter/reactions —
// mixed together so it reads like a real, varied feed. Personas and phrasing are
// invented; every name/number cited is real.
const PERSONAS = [
  { handle: "@DraftRoomLeaks", name: "Draft Room Leaks", color: "#37C871" },
  { handle: "@BudgetBuzzUK", name: "Budget Buzz", color: "#FFB627" },
  { handle: "@WaiverWireWatch", name: "Waiver Wire Watch", color: "#E8543F" },
  { handle: "@TheAuctionInsider", name: "The Auction Insider", color: "#37C871" },
  { handle: "@SquadShuffleHQ", name: "Squad Shuffle HQ", color: "#E8543F" },
  { handle: "@LastPickLarry", name: "Last Pick Larry", color: "#8AA095" },
  { handle: "@FPLGrapevine", name: "FPL Grapevine", color: "#FFB627" },
  { handle: "@ClipboardGossip", name: "Clipboard Gossip", color: "#37C871" },
];

const FAN_PERSONAS = [
  { handle: "@BenchWarmerBrian", name: "Brian", color: "#8AA095" },
  { handle: "@ArmchairGaffer", name: "The Armchair Gaffer", color: "#FFB627" },
  { handle: "@TripleCaptainTom", name: "Tom", color: "#37C871" },
  { handle: "@FPL_Degenerate", name: "FPL Degenerate", color: "#E8543F" },
  { handle: "@BigManBants", name: "Big Man Bants", color: "#8AA095" },
  { handle: "@LeagueOfItsOwn", name: "A League Of Its Own", color: "#FFB627" },
  { handle: "@ShoutyFromTheSofa", name: "Shouty From The Sofa", color: "#E8543F" },
  { handle: "@ProbablyWrongTakes", name: "Probably Wrong Takes", color: "#37C871" },
];

function pick(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

function generateRumours(state, recentMoves = []) {
  const unpicked = state.players.filter((p) => p.draftedBy === null && p.selectedByPercent > 0);
  const ownedPlayers = state.teams.flatMap((t) =>
    t.roster.map((p) => ({ ...p, teamName: t.name })),
  );
  const teamsByBudget = [...state.teams].sort(
    (a, b) => (b.remainingBudget + b.waiverBudget) - (a.remainingBudget + a.waiverBudget),
  );
  const richest = teamsByBudget[0];
  const poorest = teamsByBudget[teamsByBudget.length - 1];

  const templates = []; // each entry: () => ({ text, fan })

  // ---- Insider-style: analysis over real budgets/rosters/waiver pool ----
  if (unpicked.length) {
    templates.push(() => {
      const p = pick(unpicked);
      return { fan: false, text: `Whispers from the waiver wire: ${p.name} (${p.selectedByPercent.toFixed(1)}% selected, still unpicked) is reportedly being monitored by at least one manager.` };
    });
    templates.push(() => {
      const p = pick(unpicked);
      const t = pick(state.teams);
      return { fan: false, text: `Hearing ${t.name} could make a move for ${p.name} (${p.club}) before the next deadline. Nothing imminent.` };
    });
    templates.push(() => {
      const p = pick(unpicked);
      return { fan: false, text: `Sources close to the league suggest ${p.name} could be a shrewd pickup at this point in the season. Genuinely surprised no one's moved yet.` };
    });
  }

  if (richest && poorest && richest.id !== poorest.id) {
    templates.push(() => ({ fan: false, text: `${richest.name} remain the biggest spenders left in the league with ${richest.remainingBudget + richest.waiverBudget}m still in the bank.` }));
    templates.push(() => ({ fan: false, text: `${poorest.name} down to just ${poorest.remainingBudget + poorest.waiverBudget}m combined — running very thin on room to manoeuvre.` }));
  }

  templates.push(() => {
    const t = pick(state.teams);
    const total = t.remainingBudget + t.waiverBudget;
    return { fan: false, text: `${t.name} sitting on ${total}m combined budget right now. ${total > 30 ? "Plenty of firepower left if they want to use it." : "Not a lot of wiggle room from here."}` };
  });

  if (ownedPlayers.length) {
    const priciest = [...ownedPlayers].sort((a, b) => b.price - a.price)[0];
    const cheapest = [...ownedPlayers].sort((a, b) => a.price - b.price)[0];
    templates.push(() => ({ fan: false, text: `Biggest outlay of the draft remains ${priciest.name} — ${priciest.teamName} paid ${priciest.price}m and there's no going back now.` }));
    templates.push(() => ({ fan: false, text: `Don't sleep on ${cheapest.name} (${cheapest.price}m, ${cheapest.teamName}) — smallest fee of the whole draft, still on the books.` }));
  }

  const totalSpent = state.teams.reduce((sum, t) => sum + (100 - t.remainingBudget), 0);
  templates.push(() => ({ fan: false, text: `${totalSpent}m spent across the league so far out of a possible 600m. ${totalSpent >= 550 ? "Nearly every pound accounted for." : "Still plenty of business to be done."}` }));

  if (unpicked.length > 1) {
    templates.push(() => ({ fan: false, text: `${unpicked.length} players still up for grabs on the waiver wire. Somewhere in there is next month's best signing.` }));
  }

  templates.push(() => {
    const t = pick(state.teams);
    const n = t.roster.length;
    return { fan: false, text: `${t.name} rolling with a ${n}-player squad right now. ${n < 11 ? "A gap still needs filling before things get serious." : "Fully stocked, for now."}` };
  });

  // ---- Fan banter: generic hype, no data required ----
  const hypeLines = [
    "not ready for this season man, this league is going to be absolute carnage 😭",
    "the trash talk in the group chat has already started and the season hasn't even kicked off 💀",
    "genuinely cannot wait for gameweek 1. who's actually winning this thing",
    "some of these squads are... interesting choices. said with love",
    "reminder that whoever finishes last has to admit it publicly. no exceptions",
    "just realised how much thought everyone put into their squad and I'm slightly concerned",
  ];
  for (const line of hypeLines) templates.push(() => ({ fan: true, text: line }));

  // ---- Fan reactions to real recent squad moves ----
  if (recentMoves.length) {
    templates.push(() => {
      const m = pick(recentMoves);
      return { fan: true, text: `${m.teamName} really paid ${m.price}m for ${m.playerName}?? bold strategy 👀` };
    });
    templates.push(() => {
      const m = pick(recentMoves);
      return { fan: true, text: `ngl ${m.playerName} to ${m.teamName} is actually a solid pickup. respect` };
    });
    templates.push(() => {
      const m = pick(recentMoves);
      return { fan: true, text: `still thinking about ${m.teamName} grabbing ${m.playerName} for ${m.price}m. huge if it pays off` };
    });
  }

  // ---- Fan post-match reactions to real, finished Gameweeks ----
  const playedGws = Object.keys(state.results || {}).map((k) => Number(k.split("-")[0]));
  if (playedGws.length) {
    const latestGw = Math.max(...playedGws);
    const latestFixture = state.fixtures.find((f) => f.gw === latestGw);
    const matchResults = (latestFixture?.matches || [])
      .map(([a, b]) => {
        const res = state.results[`${latestGw}-${a}-${b}`];
        if (!res) return null;
        const teamA = state.teams.find((t) => t.id === a);
        const teamB = state.teams.find((t) => t.id === b);
        return { teamA, teamB, scoreA: res.scoreA, scoreB: res.scoreB, margin: Math.abs(res.scoreA - res.scoreB) };
      })
      .filter((r) => r !== null);

    if (matchResults.length) {
      templates.push(() => {
        const r = pick(matchResults);
        const [winner, loser, ws, ls] = r.scoreA >= r.scoreB
          ? [r.teamA, r.teamB, r.scoreA, r.scoreB]
          : [r.teamB, r.teamA, r.scoreB, r.scoreA];
        if (ws === ls) return { fan: true, text: `${r.teamA.name} ${r.scoreA} - ${r.scoreB} ${r.teamB.name}. a draw?? nobody's happy with that one` };
        if (ws - ls >= 30) return { fan: true, text: `somebody check on ${loser.name} after that gameweek 😭 ${winner.name} showed no mercy` };
        if (ws - ls <= 5) return { fan: true, text: `${winner.name} scrape past ${loser.name} by the smallest of margins. heart rate through the roof watching that one` };
        return { fan: true, text: `${winner.name} get the win over ${loser.name} this gameweek. solid, no fireworks` };
      });
    }
  }

  const count = Math.min(26, templates.length * 3);
  const rumours = [];
  for (let i = 0; i < count; i++) {
    const { fan, text } = pick(templates)();
    const persona = pick(fan ? FAN_PERSONAS : PERSONAS);
    rumours.push({ handle: persona.handle, name: persona.name, color: persona.color, text });
  }
  return rumours;
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
