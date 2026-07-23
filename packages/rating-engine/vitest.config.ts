import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    coverage: {
      provider: 'v8',
      include: ['src/**'],
      // types.ts is interface-only (zero executable statements); v8 reports it as
      // 0/0 which trips the 100% threshold. Exclude the pure-type contract file.
      exclude: ['**/*.d.ts', 'test/**', 'src/types.ts'],
      thresholds: {
        lines: 100,
        branches: 100,
        functions: 100,
        statements: 100,
      },
    },
  },
});
