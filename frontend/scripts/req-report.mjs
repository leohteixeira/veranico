// Writes `.cache/req.json` from the JSON results of Vitest and Playwright, in the shape of the
// backend's `pytest --req-report` (see `backend/tests/conftest.py`), so
// `backend/scripts/traceability.py --report` reads it unchanged:
//
//     {"tests": [{"id": "<test id>", "req": ["R-12.1-2"], "outcome": "passed"}]}
//
// `req` holds the identifiers written as `[R-<section>-<n>]` in the test's title or in the title
// of a `describe` around it. `outcome` is `passed`, `failed` or `skipped`.
//
// Inputs, each from the latest run of its tool and each optional, but not both missing:
//   .cache/vitest.json      written by `pnpm test` (see `vitest.config.ts`)
//   .cache/playwright.json  written by `pnpm e2e` (see `playwright.config.ts`)
//
// Usage, from `frontend/`: node scripts/req-report.mjs
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";
import process from "node:process";

const ROOT = join(import.meta.dirname, "..");
const CACHE = join(ROOT, ".cache");
const IDENTIFIER = /\[(R-[0-9]+(?:\.[0-9]+)*-[0-9]+)\]/g;

function identifiers(title) {
  return [...new Set([...title.matchAll(IDENTIFIER)].map((match) => match[1]))];
}

function readJson(name) {
  let text;
  try {
    text = readFileSync(join(CACHE, name), "utf8");
  } catch {
    return null;
  }
  return JSON.parse(text);
}

const VITEST_OUTCOMES = { passed: "passed", failed: "failed" };

function fromVitest(report) {
  return report.testResults.flatMap((file) =>
    file.assertionResults.map((test) => ({
      id: `frontend/${relative(ROOT, file.name)}::${test.fullName}`,
      req: identifiers(test.fullName),
      outcome: VITEST_OUTCOMES[test.status] ?? "skipped",
    })),
  );
}

const PLAYWRIGHT_OUTCOMES = { expected: "passed", flaky: "passed", unexpected: "failed" };

function fromPlaywright(report) {
  const tests = [];
  const walk = (suite, titles) => {
    for (const spec of suite.specs ?? []) {
      const title = [...titles, spec.title].join(" > ");
      for (const test of spec.tests) {
        tests.push({
          id: `frontend/e2e/${spec.file}::${title}`,
          req: identifiers(title),
          outcome: PLAYWRIGHT_OUTCOMES[test.status] ?? "skipped",
        });
      }
    }
    for (const child of suite.suites ?? []) walk(child, [...titles, child.title]);
  };
  // The top-level suites are the files: their title is the file name, not part of a test title.
  for (const file of report.suites ?? []) walk(file, []);
  return tests;
}

const vitest = readJson("vitest.json");
const playwright = readJson("playwright.json");
if (vitest === null && playwright === null) {
  process.stderr.write("req-report: no results in .cache/; run `pnpm test` or `pnpm e2e` first\n");
  process.exit(1);
}

const tests = [
  ...(vitest === null ? [] : fromVitest(vitest)),
  ...(playwright === null ? [] : fromPlaywright(playwright)),
];
mkdirSync(CACHE, { recursive: true });
writeFileSync(join(CACHE, "req.json"), `${JSON.stringify({ tests }, null, 2)}\n`);

const marked = tests.filter((test) => test.req.length > 0).length;
const failed = tests.filter((test) => test.outcome === "failed").length;
process.stdout.write(
  `req-report: ${tests.length} tests (${marked} with identifiers, ${failed} failed) -> .cache/req.json\n`,
);
