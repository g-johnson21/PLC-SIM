import { defineConfig } from 'vitest/config';

// Pure logic tests -- no component ever needs a DOM here, so the default 'node'
// environment covers everything (see the test suite's judgement calls in the report).
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
    watch: false,
  },
});
