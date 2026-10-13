const js = require("@eslint/js");
const { FlatCompat } = require("@eslint/eslintrc");
const globals = require("globals");

const compat = new FlatCompat({
  baseDirectory: __dirname,
  recommendedConfig: js.configs.recommended,
});

module.exports = [
  {
    ignores: ["node_modules/", "build/", "dist/", ".git/", "**/*.config.cjs", "**/.eslintrc.cjs", "postcss.config.cjs"],
  },
  ...compat.extends(
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react/recommended",
    "plugin:react-hooks/recommended",
    "plugin:jsx-a11y/recommended",
  ),
  {
    files: ["**/*.{js,mjs,ts,jsx,tsx}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        ...globals.browser,
        ...globals.node,
        DOMException: "readonly",
        Event: "readonly",
        EventTarget: "readonly",
        URL: "readonly",
      },
    },
    settings: { react: { version: "detect" } },
    rules: {
      "react/react-in-jsx-scope": "off",
      "react-hooks/set-state-in-effect": "off",
    },
  },
];
