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
import { POSITION_BY_ELEMENT_TYPE, computeStandings } from "../src/lib/auctionLeagueUtils.mjs";

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

// Gameweeks the admin has manually force-finalized via the admin panel — for when
// FPL's own gameweek is clearly over in real life but its `finished` flag hasn't
// caught up yet. Single-document Firestore GET returns the doc directly (not wrapped
// in `documents`, unlike the collection-list fetches above), and a 404 (no admin has
// ever forced anything) is the expected default, not an error.
async function fetchManualFinalizedGws() {
  try {
    const res = await fetch(`${FIRESTORE_BASE}/overrides/manualFinalizedGws`);
    if (!res.ok) return [];
    const body = await res.json();
    const decoded = decodeFirestoreMap(body);
    return Array.isArray(decoded.gws) ? decoded.gws.map(Number) : [];
  } catch {
    return [];
  }
}

// Latest real-world kickoff time across a gameweek's fixtures, in ms — for the
// 2-hour auto-finalize fallback below (a single match rarely runs past kickoff+2h
// once stoppage time is included).
async function fetchLatestKickoff(gwId) {
  try {
    const fixtures = await fetchJson(`${API_BASE}/fixtures/?event=${gwId}`);
    const kickoffs = fixtures
      .map((f) => f.kickoff_time)
      .filter(Boolean)
      .map((t) => new Date(t).getTime());
    return kickoffs.length ? Math.max(...kickoffs) : null;
  } catch {
    return null;
  }
}

function gwScoreForRoster(roster, liveById) {
  let score = 0;
  let matched = 0;
  let top = null;
  for (const p of roster) {
    if (p.playerId != null && liveById.has(p.playerId)) {
      const pts = liveById.get(p.playerId).stats.total_points;
      score += pts;
      matched++;
      if (!top || pts > top.points) top = { name: p.name, points: pts };
    }
  }
  return { score, matched, total: roster.length, top };
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

  // ---- Manual + time-based override for gameweeks FPL hasn't flagged finished yet ----
  // FPL's own event-level `finished` flag can lag the real final whistle by a while —
  // sometimes hours. Two independent escape hatches, either is enough to treat the
  // current gameweek as done for our purposes even though FPL itself hasn't said so:
  //  1. Admin force-finalizes it from the admin panel (Firestore overrides doc).
  //  2. Automatically, once 2+ hours have passed since its last fixture kicked off.
  // Neither ever overrides FPL once it does say finished — these only fill the gap
  // before that, and self-correct (see the results-finalization loop below) once
  // FPL's own data catches up.
  const manualFinalizedGws = new Set(await fetchManualFinalizedGws());
  let liveEventEffectivelyFinished = liveEvent ? liveEvent.finished : false;
  if (liveEvent && !liveEventEffectivelyFinished) {
    if (manualFinalizedGws.has(liveEvent.id)) {
      liveEventEffectivelyFinished = true;
    } else {
      const latestKickoff = await fetchLatestKickoff(liveEvent.id);
      if (latestKickoff != null && Date.now() - latestKickoff >= 2 * 60 * 60 * 1000) {
        liveEventEffectivelyFinished = true;
      }
    }
  }

  // ---- Freeze each gameweek's rosters the moment it goes live ----
  // Scores/standings for a gameweek must never change after the fact just because someone
  // later gets removed, added or traded — real FPL matches are scored against whoever
  // was actually rostered for that gameweek, not whoever happens to be on the roster now.
  // Without this, gwScoreForRoster() below would keep reading state.teams[i].roster (the
  // live, currently-mutating roster from Firestore), so a transfer made any time after a
  // gameweek would silently recompute — and change — that gameweek's already-reported
  // score and the standings built from it. Snapshotting once, right as a GW goes live (the
  // earliest point every sync can see it), and using that snapshot for every later score
  // computation for that GW — live or final — closes the gap. Once a result is `final`,
  // nothing recomputes it at all regardless (see the finalize loop below), so this mainly
  // protects the in-progress/provisional-final window.
  state.gwRosterSnapshots = state.gwRosterSnapshots || {};
  if (liveEvent && !state.gwRosterSnapshots[liveEvent.id]) {
    state.gwRosterSnapshots[liveEvent.id] = Object.fromEntries(
      state.teams.map((t) => [t.id, JSON.parse(JSON.stringify(t.roster))]),
    );
  }
  function rosterForGw(gwId, teamId) {
    const snap = state.gwRosterSnapshots[gwId];
    if (snap && snap[teamId]) return snap[teamId];
    // No snapshot (a gameweek that finished before this protection existed) — fall back
    // to the current roster as a one-time best-effort. Once final, it's never touched
    // again, so this can't keep drifting.
    return state.teams.find((t) => t.id === teamId)?.roster || [];
  }

  state.meta.lastFplSync = new Date().toISOString();
  state.meta.currentGameweek = liveEvent?.id ?? next?.id ?? mostRecentFinished?.id ?? null;

  const rostersInPlay = state.teams.some((t) => t.roster.length > 0);
  state.meta.seasonStatus = rostersInPlay ? "in-season" : "pre-draft";

  if (!rostersInPlay) {
    state.liveScores = null;
    state.livePlayerPoints = null;
    state.rumours = generateRumours(state, recentMoves);
    await writeFile(DATA_PATH, JSON.stringify(state, null, 2) + "\n");
    console.log("No rosters drafted yet — refreshed player pool only.");
    return;
  }

  // ---- Live, in-progress scores for the current gameweek ----
  // Computed before the Social Media feed below, so live-gameweek rumours can
  // reference these same real, current scores and standout player performances.
  // livePlayerPoints (playerId -> points, for every rostered player) ships to the
  // client so the Live Scores tab can render from these real live numbers instead
  // of the season-long eventPoints snapshot it used to rely on.
  let livePerformers = [];
  if (liveEvent && !liveEventEffectivelyFinished) {
    const live = await fetchJson(`${API_BASE}/event/${liveEvent.id}/live/`);
    const liveById = new Map(live.elements.map((e) => [e.id, e]));
    const gwFixture = state.fixtures.find((f) => f.gw === liveEvent.id);
    state.liveScores = {
      gw: liveEvent.id,
      finished: false,
      matches: (gwFixture?.matches || []).map(([a, b]) => {
        const sa = gwScoreForRoster(rosterForGw(liveEvent.id, a), liveById);
        const sb = gwScoreForRoster(rosterForGw(liveEvent.id, b), liveById);
        return { a, b, scoreA: sa.score, scoreB: sb.score };
      }),
    };

    const rosterEntries = state.teams.flatMap((t) =>
      rosterForGw(liveEvent.id, t.id).map((p) => ({ ...p, teamName: t.name })),
    );
    state.livePlayerPoints = Object.fromEntries(
      rosterEntries
        .filter((p) => p.playerId != null)
        .map((p) => [String(p.playerId), liveById.get(p.playerId)?.stats.total_points ?? 0]),
    );

    livePerformers = rosterEntries
      .map((p) => ({
        ...p,
        livePoints: p.playerId != null ? (liveById.get(p.playerId)?.stats.total_points ?? 0) : 0,
      }))
      .filter((p) => p.livePoints > 0)
      .sort((a, b) => b.livePoints - a.livePoints);
  } else {
    state.livePlayerPoints = null;
    state.liveScores = null;
  }

  // ---- Finalize results for any completed gameweek not yet recorded ----
  // Show the result as soon as FPL marks the gameweek `finished`, but keep recomputing
  // it on every sync until FPL's separate `data_checked` flag also confirms bonus points
  // — that can lag `finished` by many hours. Gating on data_checked alone (an earlier
  // version of this) left results stuck showing nothing for that whole window; locking
  // the score in on `finished` alone and never revisiting it risked freezing it a point
  // or two off if bonus points shifted afterward. This does both: available immediately,
  // self-corrects until FPL itself calls it final.
  // Also runs before generateRumours() below, not after, so a just-finalized gameweek's
  // result is reflected in the Social Media feed the same run it finishes, not one
  // sync cycle later.
  //
  // FPL's own `finished` flag is the normal trigger, but it can lag the real world (or,
  // rarely, never flip promptly). Two overrides cover that: an admin can force a specific
  // GW final via the `overrides/manualFinalizedGws` Firestore doc, and any GW is treated
  // as effectively finished once it's 2+ hours past its last real kickoff regardless of
  // what FPL reports (liveEventEffectivelyFinished, computed above). Either override marks
  // the result `final` immediately instead of waiting on `data_checked` — once FPL's own
  // `finished`/`data_checked` catch up, the normal flow below would keep recomputing until
  // they do, but since we've already frozen it as final there's nothing left to correct.
  const finishedEvents = events.filter(
    (e) =>
      e.finished ||
      manualFinalizedGws.has(e.id) ||
      (liveEvent && e.id === liveEvent.id && liveEventEffectivelyFinished),
  );
  for (const ev of finishedEvents) {
    const gwFixture = state.fixtures.find((f) => f.gw === ev.id);
    if (!gwFixture) continue;
    // Absolute rule: once a result is `final`, it is never recomputed again, for any
    // reason — not to backfill a new field, not because a transfer changed a roster.
    // That's what makes `final` actually mean final. (An older result missing
    // topScorerA/B just stays without that detail forever — recapParagraph() already
    // renders fine without it.)
    const alreadyFinal = gwFixture.matches.every(
      ([a, b]) => state.results[`${ev.id}-${a}-${b}`]?.final,
    );
    if (alreadyFinal) continue;

    const forced =
      manualFinalizedGws.has(ev.id) ||
      (liveEvent && ev.id === liveEvent.id && liveEventEffectivelyFinished && !ev.finished);
    const live = await fetchJson(`${API_BASE}/event/${ev.id}/live/`);
    const liveById = new Map(live.elements.map((e) => [e.id, e]));
    for (const [a, b] of gwFixture.matches) {
      const sa = gwScoreForRoster(rosterForGw(ev.id, a), liveById);
      const sb = gwScoreForRoster(rosterForGw(ev.id, b), liveById);
      state.results[`${ev.id}-${a}-${b}`] = {
        scoreA: sa.score,
        scoreB: sb.score,
        final: !!ev.data_checked || forced,
        topScorerA: sa.top,
        topScorerB: sb.top,
      };
    }
  }

  // Stamp the real-world moment each gameweek's results first went fully final — used by
  // the homepage to lead with the Match Recap for a day after a gameweek wraps, then fall
  // back to leading with Social Media the rest of the time. Only ever set once per GW (a
  // GW that's already stamped keeps its original stamp even as its scores keep getting
  // recomputed above until data_checked catches up).
  state.meta.gwFinalizedAt = state.meta.gwFinalizedAt || {};
  for (const ev of finishedEvents) {
    if (state.meta.gwFinalizedAt[ev.id]) continue;
    const gwFixture = state.fixtures.find((f) => f.gw === ev.id);
    if (!gwFixture) continue;
    const allFinal = gwFixture.matches.every(([a, b]) => state.results[`${ev.id}-${a}-${b}`]?.final);
    if (allFinal) state.meta.gwFinalizedAt[ev.id] = new Date().toISOString();
  }

  state.rumours = generateRumours(state, recentMoves, state.liveScores, livePerformers);

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

function pickTwoDistinct(arr) {
  const a = pick(arr);
  let b = pick(arr);
  let guard = 0;
  while (b.id === a.id && arr.length > 1 && guard < 10) {
    b = pick(arr);
    guard++;
  }
  return [a, b];
}

// Every league team gets its own fictional "FC" fanbase persona for rivalry banter —
// club-in-real-life flavor over a team name that's otherwise just a spreadsheet row.
const RIVAL_FAN_COLORS = ["#37C871", "#FFB627", "#E8543F", "#8AA095"];
function teamFanPersona(team) {
  const clean = team.name.replace(/[^a-zA-Z0-9]/g, "") || "Team";
  const variants = [
    { handle: `@${clean}FCFaithful`, name: `${team.name} FC Faithful` },
    { handle: `@${clean}Ultras`, name: `${team.name} FC Ultras` },
    { handle: `@${clean}FCDiehard`, name: `${team.name} FC Diehard` },
  ];
  const v = pick(variants);
  return { handle: v.handle, name: v.name, color: pick(RIVAL_FAN_COLORS) };
}

function generateRumours(state, recentMoves = [], liveScores = null, livePerformers = []) {
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
    "the amount of trash talk happening before a single ball has been kicked is genuinely unhinged and I am so here for it",
    "watching grown adults refresh a fantasy football website every four minutes and honestly. same",
    "someone just said 'trust the process' about their squad and I have never heard four words used more incorrectly",
    "the group chat has gone from banter to actual threats in under an hour. love this league",
    "at least two people in this league are about to learn a very expensive lesson in real time",
    "the sheer arrogance radiating off some of these picks could power a small city",
    "somebody screenshot the standings unprompted and posted it with zero context. we see you",
    "this league has more storylines already than an actual Premier League season and we're not even a gameweek in",
    "the way some of you talk about your squads versus what's actually on the pitch is a genuine crime against honesty",
    "reminder that talking a big game and having a big game are two completely different sports",
    "somebody's about to go very quiet in the group chat and we all know exactly who",
    "the confidence to price is currently at an all-time league high and reality has entered the chat",
    "nobody has apologised for anything yet but give it one bad gameweek",
    "nothing bonds six grown adults quite like mutual, deeply personal fantasy football resentment",
    "nobody in this league respects a rebuild. everybody in this league is about to need one",
    "nothing says 'healthy competition' quite like the group chat going silent for six hours after a bad result",
    "nobody warned me how personally I'd take a league where I only know these people through spreadsheets",
    "this league runs on spite, screenshots and the faint smell of unresolved beef. wouldn't change a thing",
    "somewhere in this league someone is drafting a strongly worded message they will absolutely still send",
    "the trash talk to actual football knowledge ratio in this group chat should be studied academically",
  ];
  for (const line of hypeLines) templates.push(() => ({ fan: true, text: line }));

  // ---- Club rivalry banter: every team gets a fictional fanbase trash-talking another ----
  // Real-football-style rivalry, not just spreadsheet comparisons — team-name permutations
  // alone give this section a lot of range even when the underlying numbers are flat (e.g.
  // pre-season, when every team's budget and roster look identical).
  if (state.teams.length > 1) {
    const rivalryLines = [
      (us, rival) => `${us.name} FC fans have zero respect for ${rival.name} FC and it shows every single week`,
      (us, rival) => `not to be dramatic but ${rival.name} FC still owes us an apology for last season. still waiting`,
      (us, rival) => `${rival.name} FC really thought they could just exist near ${us.name} FC. adorable`,
      (us, rival) => `every ${rival.name} FC supporter in this league needs to sit down and think about their choices`,
      (us, rival) => `${us.name} FC ultras would like to formally remind ${rival.name} FC that we exist, and we remember everything`,
      (us, rival) => `imagine supporting ${rival.name} FC. couldn't be us. genuinely could never be us`,
      (us, rival) => `${rival.name} FC fans keep talking. ${us.name} FC keeps winning arguments in the group chat, which is the only stat that matters`,
      (us, rival) => `nothing personal to ${rival.name} FC but also, respectfully, everything personal to ${rival.name} FC`,
      (us, rival) => `${rival.name} FC fans have been quiet lately. we've noticed. we're keeping notes`,
      (us, rival) => `${us.name} FC did not ask to be better than ${rival.name} FC, it just sort of happened, repeatedly, on purpose`,
      (us, rival) => `sending this on behalf of every ${us.name} FC supporter: ${rival.name} FC, this is not the callout you think it is, please stop`,
      (us, rival) => `${rival.name} FC fans in shambles again. some things never change, and honestly we hope they never do`,
      (us, rival) => `${us.name} FC supporters would like it on record that we called ${rival.name} FC's collapse weeks in advance`,
      (us, rival) => `${rival.name} FC fans have started a new bit where they pretend the table doesn't matter. very brave given where they are on it`,
      (us, rival) => `there's a very specific kind of quiet that only ${rival.name} FC fans go the week after we play them`,
      (us, rival) => `${us.name} FC did not come to make friends with ${rival.name} FC. ${us.name} FC came to make a point, repeatedly, in writing`,
      (us, rival) => `someone tell ${rival.name} FC that moral victories don't show up in the standings. we'll wait`,
      (us, rival) => `${rival.name} FC fans really said "wait for us" three weeks ago. still waiting on our end too`,
      (us, rival) => `${us.name} FC has a folder. it's called "receipts". most of it is ${rival.name} FC`,
      (us, rival) => `${rival.name} FC talking a big game for a team that's one bad week from a full identity crisis`,
      (us, rival) => `${us.name} FC would like to remind ${rival.name} FC that history remembers winners, and history has taken notes`,
    ];
    templates.push(() => {
      const [us, rival] = pickTwoDistinct(state.teams);
      return { fan: true, text: pick(rivalryLines)(us, rival), persona: teamFanPersona(us) };
    });

    // Only worth citing when there's an actual gap to point at — "we have 120m, you have
    // 120m" undercuts the trash talk instead of landing it.
    const dataRivalryLines = [
      (us, rival) => (us.remainingBudget + us.waiverBudget) - (rival.remainingBudget + rival.waiverBudget) > 0
        ? `${us.name} FC sitting on ${us.remainingBudget + us.waiverBudget}m, ${rival.name} FC scraping by on ${rival.remainingBudget + rival.waiverBudget}m. we said what we said`
        : null,
      (us, rival) => us.roster.length - rival.roster.length > 0
        ? `${us.name} FC currently ${us.roster.length} players deep, ${rival.name} FC at ${rival.roster.length}. numbers don't lie, ${rival.name} FC`
        : null,
      (us, rival) => {
        const usTop = [...us.roster].sort((a, b) => b.price - a.price)[0];
        const rivalTop = [...rival.roster].sort((a, b) => b.price - a.price)[0];
        if (!usTop || !rivalTop || usTop.price <= rivalTop.price) return null;
        return `${us.name} FC's ${usTop.name} cost more than ${rival.name} FC's entire spending on ${rivalTop.name}. spend accordingly next time, ${rival.name} FC`;
      },
    ];
    templates.push(() => {
      const [us, rival] = pickTwoDistinct(state.teams);
      const line = pick(dataRivalryLines)(us, rival);
      return { fan: true, text: line || pick(rivalryLines)(us, rival), persona: teamFanPersona(us) };
    });

    // ---- Table-based rivalry: once results exist, gloat by real league position ----
    if (Object.keys(state.results || {}).length) {
      const standings = computeStandings(state.teams, state.results);
      if (standings.length > 1) {
        const standingsRivalryLines = [
          (us, rival) => `${us.name} FC sit above ${rival.name} FC in the table right now and we intend to keep it that way`,
          (us, rival) => `${us.Pts} points to ${rival.Pts}. ${rival.name} FC, the table doesn't lie, even when you do`,
          (us, rival) => `checked the standings again just to make sure ${us.name} FC are still above ${rival.name} FC. can confirm, still are`,
          (us, rival) => `${rival.name} FC fans keep talking like they're not looking up at ${us.name} FC in the table. someone show them the standings page`,
        ];
        templates.push(() => {
          const [rowA, rowB] = pickTwoDistinct(standings);
          const aAhead = standings.indexOf(rowA) < standings.indexOf(rowB);
          const [usRow, rivalRow] = aAhead ? [rowA, rowB] : [rowB, rowA];
          const usTeam = state.teams.find((t) => t.id === usRow.id);
          if (usRow.Pts === rivalRow.Pts) {
            const rivalTeam = state.teams.find((t) => t.id === rivalRow.id);
            return { fan: true, text: pick(rivalryLines)(usTeam, rivalTeam), persona: teamFanPersona(usTeam) };
          }
          return { fan: true, text: pick(standingsRivalryLines)(usRow, rivalRow), persona: teamFanPersona(usTeam) };
        });
      }
    }
  }

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

  // ---- Live-gameweek reactions: real, currently in-progress scores and standout player performances ----
  // Only fires while a Gameweek is actually underway (liveScores is null otherwise) — the same
  // score data as the Live Scores tab, so what's posted here always matches what's shown there.
  if (liveScores && liveScores.matches.length) {
    const liveMatches = liveScores.matches.map((m) => ({
      ...m,
      teamA: state.teams.find((t) => t.id === m.a),
      teamB: state.teams.find((t) => t.id === m.b),
    }));

    templates.push(() => {
      const m = pick(liveMatches);
      if (m.scoreA === m.scoreB) return { fan: true, text: `${m.teamA.name} ${m.scoreA} - ${m.scoreB} ${m.teamB.name} right now, dead level with the gameweek still live. I physically cannot handle this` };
      const [leader, chaser, ls, cs] = m.scoreA > m.scoreB
        ? [m.teamA, m.teamB, m.scoreA, m.scoreB]
        : [m.teamB, m.teamA, m.scoreB, m.scoreA];
      return { fan: true, text: `LIVE: ${leader.name} up ${ls}-${cs} on ${chaser.name} and it's not over yet. Nothing's safe till the whistle` };
    });
    templates.push(() => {
      const m = pick(liveMatches);
      return { fan: false, text: `Gameweek ${liveScores.gw} in progress: ${m.teamA.name} ${m.scoreA} - ${m.scoreB} ${m.teamB.name}. Numbers still moving as the rest of the fixtures play out.` };
    });

    // Rivalry banter for matches with a clear live leader — the leading side's fictional
    // fanbase gloating over the trailing side's, by name, mid-match.
    const decidedLiveMatches = liveMatches.filter((m) => m.scoreA !== m.scoreB);
    if (decidedLiveMatches.length) {
      templates.push(() => {
        const m = pick(decidedLiveMatches);
        const [leader, trailer, ls, ts] = m.scoreA > m.scoreB
          ? [m.teamA, m.teamB, m.scoreA, m.scoreB]
          : [m.teamB, m.teamA, m.scoreB, m.scoreA];
        return {
          fan: true,
          text: `${trailer.name} FC fans going very quiet watching us put up ${ls}-${ts} live. take your time replying to this one`,
          persona: teamFanPersona(leader),
        };
      });
    }

    if (livePerformers.length) {
      const topPerformers = livePerformers.slice(0, 5);
      templates.push(() => {
        const p = pick(topPerformers);
        return { fan: true, text: `${p.name} sitting on ${p.livePoints} points already for ${p.teamName} this gameweek. That's ${p.price}m well spent, live and in real time 🔥` };
      });
      templates.push(() => {
        const p = pick(topPerformers);
        return { fan: false, text: `${p.name} (${p.teamName}) leads all rostered players with ${p.livePoints} points so far in Gameweek ${liveScores.gw}. Worth watching as the rest of today's fixtures wrap up.` };
      });
    }
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
        return {
          teamA,
          teamB,
          scoreA: res.scoreA,
          scoreB: res.scoreB,
          margin: Math.abs(res.scoreA - res.scoreB),
          topScorerA: res.topScorerA || null,
          topScorerB: res.topScorerB || null,
        };
      })
      .filter((r) => r !== null);

    if (matchResults.length) {
      const blowoutLines = [
        (winner, loser, ws, ls) => `${winner.name} ${ws} - ${ls} ${loser.name}. that's not a scoreline, that's a hostage situation 😭 somebody check on ${loser.name}`,
        (winner, loser, ws, ls) => `${winner.name} put ${ws - ls} points between themselves and ${loser.name}. ${loser.name} FC fans have already left the group chat, mentally if not literally`,
        (winner, loser, ws, ls) => `${loser.name} lost to ${winner.name} ${ws}-${ls} and honestly at this point it's less a result, more a diagnosis`,
      ];
      const narrowLines = [
        (winner, loser) => `${winner.name} edge ${loser.name} by the width of a single point. someone's heart genuinely stopped watching that live`,
        (winner, loser) => `${winner.name} survive ${loser.name} by the barest possible margin. nobody in either group chat is breathing normally yet`,
        (winner, loser) => `${loser.name} will replay every single lineup decision in their head this week after losing to ${winner.name} by basically nothing`,
      ];
      const standardWinLines = [
        (winner, loser) => `${winner.name} beat ${loser.name} this gameweek. professional, unbothered, mildly boring. respect the process`,
        (winner, loser) => `${winner.name} get the job done against ${loser.name}. not pretty, not dramatic, just three points and a quiet exit`,
        (winner, loser) => `${loser.name} will point to the bigger picture after that loss to ${winner.name}. ${winner.name} will point to the table`,
      ];
      const drawLines = [
        (a, b, sa) => `${a.name} ${sa} - ${sa} ${b.name}. a draw. the most cowardly result in football and both sides should be a little embarrassed`,
        (a, b, sa) => `${a.name} and ${b.name} draw ${sa}-${sa}. nobody wins, nobody loses, everybody's group chat goes quiet out of respect for the anticlimax`,
      ];

      templates.push(() => {
        const r = pick(matchResults);
        if (r.scoreA === r.scoreB) return { fan: true, text: pick(drawLines)(r.teamA, r.teamB, r.scoreA) };
        const winnerIsA = r.scoreA > r.scoreB;
        const winner = winnerIsA ? r.teamA : r.teamB;
        const loser = winnerIsA ? r.teamB : r.teamA;
        const ws = winnerIsA ? r.scoreA : r.scoreB;
        const ls = winnerIsA ? r.scoreB : r.scoreA;
        if (ws - ls >= 30) return { fan: true, text: pick(blowoutLines)(winner, loser, ws, ls) };
        if (ws - ls <= 5) return { fan: true, text: pick(narrowLines)(winner, loser) };
        return { fan: true, text: pick(standardWinLines)(winner, loser) };
      });

      // A separate callout that leans on the real per-player breakdown — who actually won
      // (or lost) their team the match, not just the final score.
      const starMatches = matchResults.filter((r) => r.topScorerA || r.topScorerB);
      if (starMatches.length) {
        templates.push(() => {
          const r = pick(starMatches);
          const winnerIsA = r.scoreA >= r.scoreB;
          const winnerTeam = winnerIsA ? r.teamA : r.teamB;
          const loserTeam = winnerIsA ? r.teamB : r.teamA;
          const star = winnerIsA ? r.topScorerA : r.topScorerB;
          if (!star) return { fan: true, text: `${winnerTeam.name} beat ${loserTeam.name} this gameweek without a single standout — just a solid team performance top to bottom` };
          return { fan: true, text: `${star.name} single-handedly dragged ${winnerTeam.name} past ${loserTeam.name} with ${star.points} points. everyone else on that roster is just along for the ride at this point` };
        });
      }
    }

    // League-wide "player of the gameweek" callout across every finished match this GW.
    const allStars = matchResults.flatMap((r) => [
      r.topScorerA ? { ...r.topScorerA, teamName: r.teamA.name } : null,
      r.topScorerB ? { ...r.topScorerB, teamName: r.teamB.name } : null,
    ]).filter(Boolean);
    if (allStars.length) {
      const gwTopScorer = [...allStars].sort((a, b) => b.points - a.points)[0];
      templates.push(() => ({ fan: false, text: `${gwTopScorer.name} was the standout performer of Gameweek ${latestGw}, putting up ${gwTopScorer.points} points for ${gwTopScorer.teamName}. Everyone else was playing for second.` }));
      templates.push(() => ({ fan: true, text: `${gwTopScorer.teamName} owning ${gwTopScorer.name} this gameweek should honestly be illegal. ${gwTopScorer.points} points and the rest of the league just had to watch` }));
    }
  }

  // Dedup by exact text within this batch — without it, a small pool of applicable
  // templates (e.g. pre-season, when every team's numbers look identical) can pick the
  // same generated line twice and the feed reads as repeating itself immediately. The pool
  // is deliberately generous (up to 150) — rivalry/banter templates redraw a random team
  // pair + line on every pick, so the real space of unique strings they can produce is in
  // the hundreds, and a big baked-in pool is what lets the homepage's Refresh button serve
  // many clicks in a row without repeating a post (see renderRumours() client-side).
  const count = Math.min(150, templates.length * 6);
  const rumours = [];
  const seenTexts = new Set();
  let attempts = 0;
  while (rumours.length < count && attempts < count * 10) {
    attempts++;
    const entry = pick(templates)();
    if (seenTexts.has(entry.text)) continue;
    seenTexts.add(entry.text);
    const persona = entry.persona || pick(entry.fan ? FAN_PERSONAS : PERSONAS);
    rumours.push({ handle: persona.handle, name: persona.name, color: persona.color, text: entry.text });
  }
  return rumours;
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
