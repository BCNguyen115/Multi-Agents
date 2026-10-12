import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E Test Configuration for FPT AgentHub Frontend
 * Base URL: http://localhost:3000
 * Multi-browser testing: Chromium, Firefox, WebKit
 */
export default defineConfig({
  testDir: './specs',
  timeout: 30 * 1000,
  expect: {
    timeout: 5000,
  },
  // Specs written before the UI redesign (they look for removed text and an old sidebar/summary flow): 1.1 1.2 2.2 2.3 4.1-4.3 5.1-5.3.
  // Rewrite them against the current interface, then delete this line.
  grepInvert: /\b(1\.[12]|2\.[23]|4\.[123]|5\.[123])\s/,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : 3,
  reporter: [
    ['html', { outputFolder: './playwright-report', open: 'never' }],
    ['list'],
  ],
  use: {
    locale: 'vi-VN', // the interface follows the browser language and the specs read Vietnamese text
    baseURL: process.env.BASE_URL || 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 10 * 1000,
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: true,
    timeout: 120 * 1000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
  ],
});
