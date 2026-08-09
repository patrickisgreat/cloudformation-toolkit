// Conventional Commits enforcement (commitlint). Linted on PRs by
// .github/workflows/commitlint.yml. See CLAUDE.md "Git workflow" for the rules.
//
// ESM (.mjs): the commitlint-github-action container runs under "type": "module",
// so a CommonJS `module.exports` config fails to load. Use `export default`.
export default {
  extends: ["@commitlint/config-conventional"],
  rules: {
    // Allow a slightly longer header for scoped template commits
    // (e.g. `feat(serverless/appsync-graphql): ...`).
    "header-max-length": [2, "always", 100],
    // Keep wrapping a convention (see CLAUDE.md) but don't hard-fail CI on long
    // body/footer lines (URLs, generated notes, pasted output).
    "body-max-line-length": [0, "always", 100],
    "footer-max-line-length": [0, "always", 100],
  },
};
