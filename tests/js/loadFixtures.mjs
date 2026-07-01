import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));

export function loadTaxScenarios() {
  const raw = readFileSync(join(__dirname, "../fixtures/tax_scenarios.json"), "utf8");
  return JSON.parse(raw).scenarios;
}

export function scenarioById(id) {
  const found = loadTaxScenarios().find((s) => s.id === id);
  if (!found) throw new Error(`Scenario not found: ${id}`);
  return found;
}
