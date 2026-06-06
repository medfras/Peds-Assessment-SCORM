import noUnsanitized from "eslint-plugin-no-unsanitized";

export default [
  noUnsanitized.configs.recommended,
  {
    files: ["static/js/**/*.js"],
    plugins: { "no-unsanitized": noUnsanitized },
    rules: {
      // Flag innerHTML assignments where dynamic content is not wrapped in escapeHTML().
      // escapeHTML() is the project-standard safe wrapper — any interpolation through
      // it is allowed. Fully hardcoded string literals are also allowed.
      // warn (not error) on existing violations in the legacy 28K-line monolith.
      // The critical AI-text and user-input paths are safe (renderMarkdown, renderAiText,
      // all use escapeHTML). Remaining warnings are .map().join() template builders using
      // game/scenario state — safe by construction but statically unverifiable.
      // Escalate to "error" and remediate all sites during Phase 4 monolith decomposition.
      "no-unsanitized/property": [
        "warn",
        {
          escape: {
            methods: ["escapeHTML", "renderMarkdown"],
          },
        },
      ],
      // Disable the method rule — insertAdjacentHTML / document.write are not used.
      "no-unsanitized/method": "off",
    },
  },
];
