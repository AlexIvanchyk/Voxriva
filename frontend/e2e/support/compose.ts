import type { Locator, Page } from "@playwright/test";
import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

let selectedTestProject: { id: string; name: string } | undefined;
const root = fileURLToPath(new URL("../../..", import.meta.url));

export function compose(...args: string[]) {
  const project = process.env.VOXRIVA_TEST_PROJECT;
  if (!project?.startsWith("voxriva-test-")) {
    throw new Error("Run this suite using make test-compose.");
  }
  return execFileSync("docker", ["compose", "-p", project, ...args], { cwd: root, encoding: "utf8", timeout: 50_000 });
}

export async function signIn(page: Page, email: string, password: string) {
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
}

export function setup() {
  test.beforeEach(async ({ page }) => {
    selectedTestProject = undefined;
    await page.goto("/");
    await signIn(page, process.env.VOXRIVA_TEST_EMAIL!, process.env.VOXRIVA_TEST_PASSWORD!);
  });
}

export const nav = (page: Page, name: string) => page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name, exact: true });

export async function createProject(page: Page, name: string) {
  await nav(page, "Projects").click();
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name", { exact: true }).fill(name);
  await dialog.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  const id = new URL(page.url()).searchParams.get("project")!;
  selectedTestProject = { id, name };
  return id;
}
export async function chooseProject(page: Page, name: string) {
  const projects = await (await page.request.get("/api/v1/projects")).json();
  selectedTestProject = projects.find((project: { name: string }) => project.name === name);
  await page.goto(`/projects?project=${selectedTestProject!.id}`);
}

export async function addMember(page: Page, email: string, name: string, role = "Viewer", password?: string, screenshot?: string) {
  await page.goto(`/members${selectedTestProject ? `?project=${selectedTestProject.id}` : ""}`);
  await page.getByRole("button", { name: "Add member", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Full name", { exact: true }).fill(name);
  await dialog.getByLabel("Email address", { exact: true }).fill(email);
  if (password) await dialog.getByLabel("Initial password", { exact: true }).fill(password);
  if (role !== "Viewer") {
    await dialog.getByRole("combobox", { name: "Project role", exact: true }).press("ArrowDown");
    await page.getByText(role, { exact: true }).last().click();
  }
  if (screenshot) {
    await dialog.getByRole("heading", { name: "Add member", exact: true }).click();
    await expect(dialog).toHaveCSS("transform", "none");
    await page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" });
  }
  await dialog.getByRole("button", { name: "Add member", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("row", { name: new RegExp(email.replaceAll(".", "\\.")) })).toBeVisible();
}
export async function createTemplate(page: Page, name: string, push = false, otherProject?: string) {
  await nav(page, "Templates").click();
  await page.getByRole("button", { name: "Create template", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Template name", { exact: true }).fill(name);
  if (push) await dialog.getByText("Push notification", { exact: true }).click();
  for (const name of [...new Set([selectedTestProject?.name, otherProject].filter((value): value is string => !!value))]) {
    const connected = dialog.getByRole("combobox", { name: "Connected projects", exact: true });
    await connected.press("ArrowDown");
    await connected.fill(name);
    await page.locator(".ant-select-dropdown:visible").getByText(name, { exact: true }).last().click();
  }
  await dialog.getByRole("heading", { name: "Create template", exact: true }).click();
  await dialog.getByRole("button", { name: "Create template", exact: true }).click();
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  return new URL(page.url()).pathname.split("/").at(-1)!;
}
export async function editCode(page: Page, label: string, source: string) {
  const editor = page.getByRole("textbox", { name: label, exact: true });
  if (["Email subject", "Push title", "Push body"].includes(label)) { await editor.fill(source); return; }
  const tabs: Record<string, string> = { "Schema JSON": "Variables", "Fixture JSON": "Test data", "Runtime defaults JSON": "Runtime defaults", "Push data": "Content" };
  if (tabs[label]) {
    await page.getByRole("tab", { name: tabs[label], exact: true }).click();
    if (!await editor.isVisible()) await page.getByRole("tabpanel", { name: tabs[label], exact: true }).getByText("Advanced JSON", { exact: true }).click();
  }
  await page.getByRole("code").filter({ has: editor }).click();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.insertText(source);
}
export async function setVariables(page: Page) {
  await page.getByRole("tab", { name: "Variables", exact: true }).click();
  await editCode(page, "Schema JSON", '{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","properties":{"name":{"type":"string"}},"required":["name"],"additionalProperties":false}');
  await page.getByRole("tab", { name: "Test data", exact: true }).click();
  await editCode(page, "Fixture JSON", '{"name":"Taylor Synthetic"}');
  await page.getByRole("tab", { name: "Content", exact: true }).click();
}
export async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
}


// Ant Design virtualizes Select options; keyboard traversal renders targets outside
// the initial viewport without assuming a fixed number or order of projects.
export async function chooseOption(page: Page, control: Locator, text: string) {
  await control.press("ArrowDown");
  const option = page.locator(".ant-select-dropdown:visible").getByText(text, { exact: true }).last();
  for (let step = 0; step < 100 && !await option.isVisible(); step++) {
    await control.press("ArrowDown");
  }
  await expect(option).toBeVisible();
  await option.click();
}
