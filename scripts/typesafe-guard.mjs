// Sanity-checks the FPL data sync's output before update-fpl-data.yml auto-commits
// it. Routine site updates (feed wording, standings, live scores) are meant to
// publish themselves with nobody checking, but team budgets and roster sizes are
// the one carve-out where a human should look before anything ships — this asks
// TypeSafe's Jev model (docs.typesafe.ai) a single yes/no judgment on a small
// before/after summary of exactly those fields, and fails the workflow (skipping
// the commit step) when the sync looks like it broke something rather than just
// changed it.
//
// Fails open — never blocks the commit — when TYPESAFE_API_KEY isn't set, when
// there's no prior committed data to compare against, or if the API call itself
// errors. A missing key or a vendor outage shouldn't stop a routine sync.
import { execSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_PATH = path.join(__dirname, "..", "src", "data", "auctionLeague.json");
const API_KEY = process.env.TYPESAFE_API_KEY;
const CORRUPTION_THRESHOLD = 0.7;

function summarize(state) {
  return {
    currentGameweek: state?.meta?.currentGameweek ?? null,
    seasonStatus: state?.meta?.seasonStatus ?? null,
    playerCount: state?.players?.length ?? 0,
    teams: (state?.teams || []).map((t) => ({
      name: t.name,
      remainingBudget: t.remainingBudget,
      waiverBudget: t.waiverBudget,
      rosterSize: t.roster?.length ?? 0,
    })),
  };
}

function loadPreviousState() {
  try {
    const raw = execSync("git show HEAD:src/data/auctionLeague.json", { encoding: "utf8" });
    return JSON.parse(raw);
  } catch {
    return null; // first run, or the file isn't committed yet — nothing to compare
  }
}

async function main() {
  if (!API_KEY) {
    console.log("TYPESAFE_API_KEY not set — skipping sync sanity check.");
    return;
  }

  const previous = loadPreviousState();
  if (!previous) {
    console.log("No prior committed data to compare — skipping sync sanity check.");
    return;
  }
  const next = JSON.parse(await readFile(DATA_PATH, "utf8"));

  const before = summarize(previous);
  const after = summarize(next);

  let result;
  try {
    const res = await fetch("https://api.typesafe.ai/v1/systemone", {
      method: "POST",
      headers: { Authorization: `Bearer ${API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "jev-latest",
        state: JSON.stringify({ before, after }),
        questions: {
          looksCorrupted: {
            type: "noul",
            question:
              "This is a before/after summary of an auction fantasy football league's team budgets and roster sizes after an automated data sync. Ignoring plausible in-season changes (budgets going down, rosters growing), does the 'after' state look corrupted or wrong — e.g. a team's budget or roster wiped to zero/null when it wasn't before, a budget that went sharply negative, or a roster size that dropped without any transfer explaining it?",
          },
        },
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    result = await res.json();
  } catch (err) {
    console.log(`TypeSafe check failed (${err.message}) — failing open, proceeding with commit.`);
    return;
  }

  const probability = result?.answers?.looksCorrupted?.probability ?? 0;
  console.log(`TypeSafe corruption-likelihood: ${probability}`);
  if (probability >= CORRUPTION_THRESHOLD) {
    console.error(
      "TypeSafe flagged this sync's team budgets/rosters as likely corrupted — holding the commit for review.",
    );
    process.exit(1);
  }
}

main();
