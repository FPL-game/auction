// One-off script that seeds src/data/auctionLeague.json for a fresh season.
// Run manually with `node scripts/init-auction-league-data.mjs` — it will NOT
// overwrite an existing data file, so re-running mid-season is a no-op.
import { writeFile, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  defaultTeams,
  generateFixtures,
} from "../src/lib/auctionLeagueUtils.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_PATH = path.join(__dirname, "..", "src", "data", "auctionLeague.json");

// Seed pool used until the first live FPL sync replaces it with the full player list.
const SEED_PLAYERS = [
  ["Erling Haaland", "FWD", "Man City"], ["Mohamed Salah", "MID", "Liverpool"], ["Bukayo Saka", "MID", "Arsenal"],
  ["Cole Palmer", "MID", "Chelsea"], ["Son Heung-min", "MID", "Spurs"], ["Ollie Watkins", "FWD", "Aston Villa"],
  ["Alexander Isak", "FWD", "Newcastle"], ["Phil Foden", "MID", "Man City"], ["Bruno Fernandes", "MID", "Man Utd"],
  ["Martin Odegaard", "MID", "Arsenal"], ["Kai Havertz", "FWD", "Arsenal"], ["Julian Alvarez", "FWD", "Atletico"],
  ["Trent Alexander-Arnold", "DEF", "Real Madrid"], ["Virgil van Dijk", "DEF", "Liverpool"], ["William Saliba", "DEF", "Arsenal"],
  ["Gabriel Magalhaes", "DEF", "Arsenal"], ["Reece James", "DEF", "Chelsea"], ["Pedro Porro", "DEF", "Spurs"],
  ["Alisson Becker", "GK", "Liverpool"], ["Ederson", "GK", "Man City"], ["David Raya", "GK", "Arsenal"],
  ["Nick Pope", "GK", "Newcastle"], ["Jordan Pickford", "GK", "Everton"], ["Emiliano Martinez", "GK", "Aston Villa"],
  ["Bryan Mbeumo", "MID", "Man Utd"], ["Jarrod Bowen", "MID", "West Ham"], ["Morgan Rogers", "MID", "Aston Villa"],
  ["Chris Wood", "FWD", "Nott'm Forest"], ["Yoane Wissa", "FWD", "Newcastle"], ["Matheus Cunha", "FWD", "Man Utd"],
  ["Antoine Semenyo", "MID", "Bournemouth"], ["Justin Kluivert", "MID", "Bournemouth"], ["Anthony Gordon", "MID", "Newcastle"],
  ["Jean-Philippe Mateta", "FWD", "Crystal Palace"], ["Danny Welbeck", "FWD", "Brighton"], ["Yankuba Minteh", "MID", "Brighton"],
  ["Joao Pedro", "FWD", "Chelsea"], ["Nicolas Jackson", "FWD", "Chelsea"], ["Enzo Fernandez", "MID", "Chelsea"],
  ["Declan Rice", "MID", "Arsenal"], ["Rodri", "MID", "Man City"], ["Josko Gvardiol", "DEF", "Man City"],
  ["Ruben Dias", "DEF", "Man City"], ["Milos Kerkez", "DEF", "Liverpool"], ["Levi Colwill", "DEF", "Chelsea"],
  ["Destiny Udogie", "DEF", "Spurs"], ["Cristian Romero", "DEF", "Spurs"], ["Murillo", "DEF", "Nott'm Forest"],
  ["Nikola Milenkovic", "DEF", "Nott'm Forest"], ["Amad Diallo", "MID", "Man Utd"], ["Jacob Murphy", "MID", "Newcastle"],
  ["Iliman Ndiaye", "MID", "Everton"], ["Marcus Rashford", "MID", "Barcelona"],
];

async function exists(p) {
  try {
    await readFile(p);
    return true;
  } catch {
    return false;
  }
}

async function main() {
  if (await exists(DATA_PATH)) {
    console.log(`${DATA_PATH} already exists — leaving it alone.`);
    return;
  }

  const teams = defaultTeams();
  const state = {
    teams,
    fixtures: generateFixtures(teams),
    results: {},
    players: SEED_PLAYERS.map(([name, pos, club]) => ({
      id: null,
      name,
      pos,
      club,
      pts: 0,
      draftedBy: null,
    })),
    meta: {
      seasonStatus: "pre-draft",
      currentGameweek: null,
      lastUpdated: null,
      lastFplSync: null,
    },
  };

  await writeFile(DATA_PATH, JSON.stringify(state, null, 2) + "\n");
  console.log(`Wrote ${DATA_PATH}`);
}

main();
