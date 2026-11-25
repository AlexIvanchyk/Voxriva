import { expect, test } from "@playwright/test";
import { createProject, createTemplate, editCode, nav, setup, signOut } from "./support/compose";

setup();

test("browser smoke authenticates, saves a template and restores notification search", async ({ page }, testInfo) => {
  const suffix = testInfo.project.name;
  await createProject(page, `Browser smoke ${suffix}`);
  const templateId = await createTemplate(page, `Browser template ${suffix}`);
  const subject = `Saved from ${suffix}`;
  await editCode(page, "Email subject", subject);
  await expect(page.getByText("Unsaved changes", { exact: true })).toBeVisible();
  const [saved] = await Promise.all([
    page.waitForResponse((response) => response.request().method() === "PUT" && new URL(response.url()).pathname === `/api/v1/templates/${templateId}/draft`),
    page.getByRole("button", { name: /^(?:loading )?Save draft$/ }).click(),
  ]);
  expect(saved.status(), await saved.text()).toBe(200);
  expect((await saved.json()).draft.subject).toBe(subject);
  await expect(page.getByText("Saved draft", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("textbox", { name: "Email subject", exact: true })).toHaveValue(subject);

  await nav(page, "Notifications").click();
  await expect(page.getByRole("heading", { name: "Notifications", exact: true })).toBeVisible();
  const search = `browser-smoke-${suffix}@example.test`;
  await page.getByRole("searchbox", { name: "Search recipient email", exact: true }).fill(search);
  const [filtered] = await Promise.all([
    page.waitForResponse((response) => {
      const url = new URL(response.url());
      return response.request().method() === "GET" && url.pathname === "/api/v1/notifications" && url.searchParams.get("recipient_email") === search;
    }),
    page.getByRole("searchbox", { name: "Search recipient email", exact: true }).press("Enter"),
  ]);
  expect(filtered.status(), await filtered.text()).toBe(200);
  expect((await filtered.json()).total).toBe(0);
  await expect(page.getByText("No notifications match these filters. Submit a notification using an environment API key to begin.", { exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("recipient_email")).toBe(search);
  await page.reload();
  await expect(page.getByRole("searchbox", { name: "Search recipient email", exact: true })).toHaveValue(search);
  await expect(page.getByText("No notifications match these filters. Submit a notification using an environment API key to begin.", { exact: true })).toBeVisible();
  await signOut(page);
  await expect(page.getByRole("navigation", { name: "Main navigation" })).toHaveCount(0);
});
