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

// Recent add/trade moves, for fan-reaction posts in the Social Media feed.
async function fetchRecentDraftLog() {
  const res = await fetch(`${FIRESTORE_BASE}/draftLog`);
  if (!res.ok) return [];
  const body = await res.json();
  return (body.documents || [])
    .map((doc) => decodeFirestoreMap(doc))
    .filter((d) => d.type === "add" || d.type === "trade")
    .slice(-15);
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
      return { fan: false, text: `EXCLUSIVE: ${p.name} has been sitting on the waiver wire at ${p.selectedByPercent.toFixed(1)}% selected while every manager in this league pretends not to notice. Someone's about to look very smart.` };
    });
    templates.push(() => {
      const p = pick(unpicked);
      const t = pick(state.teams);
      return { fan: false, text: `Told ${t.name} have been "circling" ${p.name} (${p.club}) for two straight weeks now. At what point does circling just become cowardice.` };
    });
    templates.push(() => {
      const p = pick(unpicked);
      return { fan: false, text: `A source close to the situation (me, staring at the waiver list) confirms ${p.name} is a free hit sitting right there in plain sight. Baffling nobody's pulled the trigger.` };
    });
  }

  if (richest && poorest && richest.id !== poorest.id) {
    templates.push(() => ({ fan: false, text: `${richest.name} sitting on ${richest.remainingBudget + richest.waiverBudget}m like a dragon guarding gold it has no plan for. Do something with it.` }));
    templates.push(() => ({ fan: false, text: `${poorest.name} down to ${poorest.remainingBudget + poorest.waiverBudget}m combined. Financially, this is a crime scene.` }));
  }

  templates.push(() => {
    const t = pick(state.teams);
    const total = t.remainingBudget + t.waiverBudget;
    return { fan: false, text: `${t.name} sitting on ${total}m right now. ${total > 30 ? "Enough firepower to change this league and they're just... not." : "Basically down to loose change and vibes at this point."}` };
  });

  if (ownedPlayers.length) {
    const priciest = [...ownedPlayers].sort((a, b) => b.price - a.price)[0];
    const cheapest = [...ownedPlayers].sort((a, b) => a.price - b.price)[0];
    templates.push(() => ({ fan: false, text: `${priciest.teamName} dropped ${priciest.price}m on ${priciest.name} and there is no refund policy in this league. Committed now, for better or worse.` }));
    templates.push(() => ({ fan: false, text: `${cheapest.name} cost ${cheapest.teamName} just ${cheapest.price}m. Absolute daylight robbery and everyone's too polite to say it out loud.` }));
  }

  const totalSpent = state.teams.reduce((sum, t) => sum + (100 - t.remainingBudget), 0);
  templates.push(() => ({ fan: false, text: `${totalSpent}m of a possible 600m spent league-wide. ${totalSpent >= 550 ? "Every pound accounted for — nobody has anything left to hide behind." : "Still real money on the table and somebody is sitting on it out of pure stubbornness."}` }));

  if (unpicked.length > 1) {
    templates.push(() => ({ fan: false, text: `${unpicked.length} players still unclaimed on the waiver wire. One of them wins somebody a title and this whole league is too busy scrolling to notice.` }));
  }

  templates.push(() => {
    const t = pick(state.teams);
    const n = t.roster.length;
    return { fan: false, text: `${t.name} currently running ${n} players deep. ${n < 11 ? "There is a hole in this squad you could drive a bus through." : "Fully loaded — for now. Ask again after the next waiver deadline."}` };
  });

  // ---- Fan banter: generic hype, no data required ----
  const hypeLines = [
    "not emotionally prepared for gameweek 1, my heart genuinely cannot take this league 😭",
    "the group chat is already 400 messages deep and literally NOTHING has happened yet. imagine week 12",
    "someone's captain pick is about to end a real friendship. calling it now",
    "watched three squads get announced back to back and I need to lie down",
    "the confidence some of you are showing after the picks you made is genuinely inspiring behaviour",
    "reminder: whoever finishes bottom has to change their profile picture to the trophy for a month. no exceptions, no appeals",
    "I've decided who I'm rooting against and it's whoever's having the most fun doing well. sorry",
    "just did the maths on somebody's spending and I have never seen anyone go all in like that. reckless. iconic. reckless",
    "everyone in this league thinks they drafted the smart squad. statistically most of you are just wrong 💀",
    "the gap between how confident people sound in the group chat and how their squads actually look is not adding up 🔥",
    "genuinely losing sleep over gameweek 1 and I don't think that counts as normal behaviour anymore",
    "somebody in this league is about to get bullied for a full calendar year over one decision. build a bridge",
  ];
  for (const line of hypeLines) templates.push(() => ({ fan: true, text: line }));

  // ---- Fan reactions to real recent squad moves ----
  const recentAdds = recentMoves.filter((m) => m.type === "add");
  const recentTrades = recentMoves.filter((m) => m.type === "trade");

  if (recentAdds.length) {
    templates.push(() => {
      const m = pick(recentAdds);
      return { fan: true, text: `${m.teamName} spent ${m.price}m on ${m.playerName} and I need everyone to just sit with that number for a second 👀` };
    });
    templates.push(() => {
      const m = pick(recentAdds);
      return { fan: true, text: `${m.teamName} picking up ${m.playerName} is either genius or a cry for help. genuinely could be both` };
    });
    templates.push(() => {
      const m = pick(recentAdds);
      return { fan: true, text: `can't stop thinking about ${m.teamName} dropping ${m.price}m on ${m.playerName}. that's not a signing, that's a personality trait now` };
    });
    templates.push(() => {
      const m = pick(recentAdds);
      return { fan: true, text: `${m.playerName} to ${m.teamName} for ${m.price}m. bold. unhinged. slightly evil. I respect it 🔥` };
    });
  }

  // ---- Fan and insider reactions to real recent trades ----
  if (recentTrades.length) {
    templates.push(() => {
      const t = pick(recentTrades);
      const aCount = (t.playersAToB || []).length;
      const bCount = (t.playersBToA || []).length;
      return { fan: true, text: `${t.teamAName} and ${t.teamBName} just pulled off a ${aCount}-for-${bCount} trade and I have several questions 👀` };
    });
    templates.push(() => {
      const t = pick(recentTrades);
      const names = (t.playersAToB || []).map((p) => p.name).join(" and ");
      if (!names) return { fan: true, text: `${t.teamAName} and ${t.teamBName} just completed a trade and nobody in the group chat can stop talking about it` };
      return { fan: true, text: `${t.teamAName} straight up gave away ${names} in that trade. brave or insane, genuinely no in-between` };
    });
    templates.push(() => {
      const t = pick(recentTrades);
      return { fan: false, text: `Confirmed: ${t.teamAName} and ${t.teamBName} completed a trade this week. Full details still filtering through the league — sources say both sides are already calling it a win.` };
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
        if (ws === ls) return { fan: true, text: `${r.teamA.name} ${r.scoreA} - ${r.scoreB} ${r.teamB.name}. a draw. the most cowardly result in football and both sides should be a little embarrassed` };
        if (ws - ls >= 30) return { fan: true, text: `${winner.name} ${ws} - ${ls} ${loser.name}. that's not a scoreline, that's a hostage situation 😭 somebody check on ${loser.name}` };
        if (ws - ls <= 5) return { fan: true, text: `${winner.name} edge ${loser.name} by the width of a single point. someone's heart genuinely stopped watching that live` };
        return { fan: true, text: `${winner.name} beat ${loser.name} this gameweek. professional, unbothered, mildly boring. respect the process` };
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
