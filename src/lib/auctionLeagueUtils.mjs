// Shared, framework-agnostic helpers for The Auction League.
// Imported by both the Astro page (build time) and the Node scripts
// (scripts/init-auction-league-data.mjs, scripts/update-fpl-data.mjs).

export const TEAM_NAMES = ["Abhilash", "Adi", "Chase", "Malhar", "Nikhil", "Varun"];
export const START_BUDGET = 100;
export const START_WAIVER = 20;
export const TOTAL_GAMEWEEKS = 38;

export function defaultTeams() {
  return TEAM_NAMES.map((name, i) => ({
    id: i + 1,
    name,
    remainingBudget: START_BUDGET,
    waiverBudget: START_WAIVER,
    roster: [], // {playerId, name, pos, club, price}
  }));
}

// Circle method round robin: 6 teams -> 5 rounds x 3 matches, repeating across 38 GWs.
export function generateFixtures(teams) {
  const ids = teams.map((t) => t.id);
  const n = ids.length;
  const rounds = [];
  const arr = ids.slice(1);
  const fixed = ids[0];
  for (let r = 0; r < n - 1; r++) {
    const round = [];
    const rotated = [fixed, ...arr];
    for (let i = 0; i < n / 2; i++) {
      round.push([rotated[i], rotated[n - 1 - i]]);
    }
    round.forEach((m) => {
      if (r % 2 === 1) m.reverse();
    });
    rounds.push(round);
    arr.push(arr.shift());
  }
  const gameweeks = [];
  for (let gw = 1; gw <= TOTAL_GAMEWEEKS; gw++) {
    const roundIdx = (gw - 1) % rounds.length;
    gameweeks.push({ gw, matches: rounds[roundIdx] });
  }
  return gameweeks;
}

export function teamName(teams, id) {
  const t = teams.find((x) => x.id === id);
  return t ? t.name : "TBD";
}

export function computeStandings(teams, results) {
  const table = {};
  teams.forEach((t) => {
    table[t.id] = { id: t.id, name: t.name, P: 0, W: 0, D: 0, L: 0, PF: 0, PA: 0, Pts: 0 };
  });
  Object.keys(results || {}).forEach((key) => {
    const [, a, b] = key.split("-").map(Number);
    const res = results[key];
    if (!res) return;
    const ta = table[a];
    const tb = table[b];
    if (!ta || !tb) return;
    ta.P++;
    tb.P++;
    ta.PF += res.scoreA;
    ta.PA += res.scoreB;
    tb.PF += res.scoreB;
    tb.PA += res.scoreA;
    if (res.scoreA > res.scoreB) {
      ta.W++;
      tb.L++;
      ta.Pts += 3;
    } else if (res.scoreA < res.scoreB) {
      tb.W++;
      ta.L++;
      tb.Pts += 3;
    } else {
      ta.D++;
      tb.D++;
      ta.Pts += 1;
      tb.Pts += 1;
    }
  });
  return Object.values(table).sort(
    (x, y) => y.Pts - x.Pts || (y.PF - y.PA) - (x.PF - x.PA) || y.PF - x.PF,
  );
}

export const POSITION_BY_ELEMENT_TYPE = { 1: "GK", 2: "DEF", 3: "MID", 4: "FWD" };
