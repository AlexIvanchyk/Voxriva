import { defineConfig, devices } from "@playwright/test";

const browserMatrix = process.env.VOXRIVA_E2E_BROWSER_MATRIX === "1";
const smoke = "**/28-browser-smoke.spec.ts";

export default defineConfig({
  testDir: "./e2e",
  // The full suite deliberately restarts shared services. Matrix projects use
  // only an isolated UI smoke and remain serial against their own test stack.
  workers: 1,
  timeout: 120_000,
  use: {
    actionTimeout: 15_000,
    ignoreHTTPSErrors: process.env.VOXRIVA_TEST_SELF_SIGNED_TLS === "1",
    baseURL: process.env.VOXRIVA_TEST_URL ?? "http://127.0.0.1:18080",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", testIgnore: smoke, use: { browserName: "chromium" } },
    ...(browserMatrix ? [
      { name: "firefox", testMatch: smoke, use: { browserName: "firefox" as const } },
      { name: "webkit", testMatch: smoke, use: { browserName: "webkit" as const } },
      { name: "mobile-chromium", testMatch: smoke, use: { ...devices["Pixel 5"], browserName: "chromium" as const } },
    ] : []),
  ],
});
