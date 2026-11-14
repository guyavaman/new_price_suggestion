import { defineConfig, devices } from '@playwright/test';

/**
 * Browser tests for the critical paths, against the real backend serving the production build.
 * Every run starts the API on a throwaway data folder seeded with the demo business, so the
 * tests never touch your local data and always start from the same state.
 *
 *   npx ng build && npx playwright test        (backend deps installed, see README)
 */
const PORT = 8123;
const STORE = 'e2e/.store';

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: false, // one seeded business, tests change it: run in order
  workers: 1,
  retries: process.env['CI'] ? 1 : 0,
  reporter: process.env['CI'] ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://localhost:${PORT}`,
    locale: 'he-IL',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `rm -rf ${STORE} && cd ../backend && STORE_DIR=../frontend/${STORE} SEED_DEMO=1 PUBLIC_BASE_URL=http://localhost:${PORT} ` +
      `FRONTEND_DIST=../frontend/dist/crm/browser python3 -m uvicorn app.main:app --port ${PORT}`,
    url: `http://localhost:${PORT}/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
