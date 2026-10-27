// Lint: npm run lint. ESLint's recommended rules plus the two classic React hooks rules; the plugin's React
// Compiler rules (its "recommended" set in v7) are left out because the app does not use the compiler.
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

export default [
  {
    files: ["**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...js.configs.recommended.rules,
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
      // components used only in JSX look unused to the core rule; the capitalised name marks them
      "no-unused-vars": ["error", { varsIgnorePattern: "^[A-Z_]" }],
    },
  },
  { files: ["vite.config.js", "eslint.config.js"], languageOptions: { globals: globals.node } },
  { files: ["dashboard/public/sw.js"], languageOptions: { globals: globals.serviceworker } },
];
