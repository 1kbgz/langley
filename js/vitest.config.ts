import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    include: ["tests/**/*.{test,spec}.{ts,tsx}"],
    setupFiles: ["tests/setup.ts"],
  },
  esbuild: {
    jsx: "automatic",
  },
});
