import globals from "globals";

export default [{
  files: ["web/**/*.js"],
  ignores: ["web/vendor/**"],
  languageOptions: {
    ecmaVersion: "latest",
    sourceType: "script",
    globals: {
      ...globals.browser,
      Chart: "readonly",
      DOMPurify: "readonly",
      FullCalendar: "readonly",
      AUTH_PARAMS: "readonly",
      AUTH_API_BASE: "readonly",
      mostraErrorePagina: "readonly",
      urlConNext: "readonly",
      collegaGoogle: "readonly",
      vaiADestinazione: "readonly",
    },
  },
  rules: { "no-undef": "error", "no-dupe-args": "error", "no-unreachable": "error" },
}];
