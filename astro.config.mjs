import { defineConfig } from 'astro/config';

// Deployed to GitHub Pages at https://fpl-game.github.io/auction/ via
// .github/workflows/deploy-pages.yml — base must match the repo name's
// exact casing, since GitHub Pages project-site paths are case-sensitive.
export default defineConfig({
  site: 'https://fpl-game.github.io',
  base: '/auction',
});
