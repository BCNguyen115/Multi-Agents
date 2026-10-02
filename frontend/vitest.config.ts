import { defineConfig } from 'vitest/config';

// Unit tests only: Playwright specs (tests/e2e/**/*.spec.ts) must not be collected by vitest.
export default defineConfig({
  test: { include: ['tests/unit/**/*.test.ts'], environment: 'node' },
});
