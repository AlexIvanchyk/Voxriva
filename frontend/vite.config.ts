import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const api = process.env.VOXRIVA_DEV_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: { "/api": api, "/health": api, "/metrics": api },
  },
  test: {
    testTimeout: 10_000,
    maxWorkers: 1,
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test-setup.ts"],
  },
});
