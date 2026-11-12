// Fails when the built files contain the mock layer. `src/test/mocks/handlers.ts` exports a
// sentinel string that nothing else uses, so finding it in `dist/` means test code was bundled.
//
// Usage, from `frontend/` after `vite build`: node scripts/check-dist.mjs
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import process from "node:process";

// Kept equal to `MOCK_SENTINEL` by a test in `src/test/mocks/handlers.test.ts`.
const SENTINEL = "veranico-development-mock-layer";
const DIST = join(import.meta.dirname, "..", "dist");

let files;
try {
  files = readdirSync(DIST, { recursive: true, withFileTypes: true }).filter((entry) =>
    entry.isFile(),
  );
} catch {
  process.stderr.write("check-dist: dist/ does not exist; run the build first\n");
  process.exit(1);
}

const found = files
  .map((entry) => join(entry.parentPath, entry.name))
  .filter((path) => readFileSync(path).includes(SENTINEL));

if (found.length > 0) {
  process.stderr.write(`check-dist: the mock layer is in the build:\n${found.join("\n")}\n`);
  process.exit(1);
}
process.stdout.write(`check-dist: ${files.length} built files, no mock layer\n`);
