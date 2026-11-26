import { expect, test } from "@playwright/test";
import { compose, setup } from "./support/compose";

setup();

test("serves the dashboard and records the initial migration in persistent PostgreSQL", async ({ page, request }) => {
  const database = ["exec", "-T", "postgres", "psql", "-U", "voxriva", "-d", "voxriva", "-Atc"];
  await page.goto("/");
  await expect(page.getByText("API version 0.1.1")).toBeVisible();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await expect(page.getByText("Ready", { exact: true })).toHaveCount(3);
  expect(compose(...database, "SELECT version_num FROM alembic_version").trim()).toBe("0013_account_mfa");
  compose("up", "-d", "--force-recreate", "--no-deps", "postgres");
  await expect.poll(async () => (await request.get("/health/ready")).status(), { timeout: 25_000 }).toBe(200);
  expect(compose(...database, "SELECT version_num FROM alembic_version").trim()).toBe("0013_account_mfa");

  await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "System Health", exact: true }).click();
  await page.reload();
  await expect(page.getByRole("heading", { name: "System Health" })).toBeVisible();
  await expect(page.getByRole("row", { name: /migrate.*Completed.*No health check/ })).toBeVisible({ timeout: 20_000 });
  expect((await request.get("/api/unknown")).status()).toBe(404);
  expect((await request.get("/metrics")).headers()["content-type"]).toContain("text/plain");
});

test("reports real container changes and preserves last known state during outages", async ({ page, request }) => {
  await page.goto("/system/health");
  const redis = page.getByRole("row", { name: /voxriva-test-.*-redis-1/ });
  const collector = page.getByRole("row", { name: /voxriva-test-.*-collector-1/ });
  await expect(redis.getByText("Running", { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(collector.getByText("Running", { exact: true })).toBeVisible();

  try {
    compose("stop", "redis");
    await expect(redis.getByText("Exited", { exact: true })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByLabel("Dependency readiness").getByText("Unavailable", { exact: true })).toBeVisible();
    expect((await request.get("/health/live")).status()).toBe(200);
    expect((await request.get("/health/ready")).status()).toBe(503);
  } finally {
    compose("start", "redis");
  }
  await expect(redis.getByText("Running", { exact: true })).toBeVisible({ timeout: 20_000 });

  try {
    compose("stop", "collector");
    await expect(page.getByText("Container data is stale")).toBeVisible({ timeout: 25_000 });
    await expect(redis).toBeVisible();
  } finally {
    compose("start", "collector");
  }
  await expect(page.getByText("Container data is stale")).toHaveCount(0, { timeout: 20_000 });

  try {
    compose("stop", "api");
    await expect(page.getByText("API connection unavailable")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("Container data is stale")).toBeVisible();
    await expect(redis).toBeVisible();
  } finally {
    compose("start", "api");
  }
  await expect(page.getByText("API connection unavailable")).toHaveCount(0, { timeout: 25_000 });
});
