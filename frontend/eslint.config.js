import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  // `design-reference/` is the approved visual reference, not application code.
  // `src/api/schema.d.ts` is generated from `backend/openapi.json`.
  {
    ignores: [
      "dist/",
      "design-reference/",
      "node_modules/",
      "src/api/schema.d.ts",
      ".cache/",
      "playwright-report/",
      "test-results/",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.strict,
  reactHooks.configs.flat.recommended,
  {
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
    },
  },
);
