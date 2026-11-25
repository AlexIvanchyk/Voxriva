import type { Locator, Page } from "@playwright/test";
import { expect, test } from "@playwright/test";
import { compose, createProject, nav, setup } from "./support/compose";

setup();
const sql = (query: string) => compose("exec", "-T", "postgres", "psql", "-U", "voxriva", "-d", "voxriva", "-Atc", query).trim();
const card = (page: Page, name: string) => page.locator("article.project-card").filter({ has: page.getByRole("heading", { name, exact: true }) });
const row = (page: Page, name: string) => page.getByRole("row").filter({ has: page.getByText(name, { exact: true }) });
const confirmation = (page: Page) => page.locator(".ant-popconfirm:visible");
const draft = { subject: "Synthetic resource history", text: "Synthetic resource lifecycle fixture", variable_schema: { type: "object", properties: {}, additionalProperties: false }, preview_context: {} };

async function api(page: Page) {
  const headers = { "X-CSRF-Token": (await (await page.request.get("/api/v1/auth/session")).json()).csrf_token };
  return { headers, async create(path: string, data: object) {
    const response = await page.request.post(`/api/v1${path}`, { headers, data });
    expect(response.status(), await response.text()).toBe(201);
    return response.json();
  } };
}
async function rename(page: Page, trigger: Locator, title: string, name: string, save: boolean) {
  await trigger.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: title, exact: true })).toBeVisible();
  await dialog.getByLabel("Name", { exact: true }).fill(name);
  await dialog.getByRole("button", { name: save ? "Save changes" : "Cancel", exact: true }).click();
  await expect(dialog).toHaveCount(0);
}
async function cancelDelete(page: Page, trigger: Locator, description: string) {
  await trigger.click();
  await expect(confirmation(page).getByText(description, { exact: true })).toBeVisible();
  await confirmation(page).getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(confirmation(page)).toHaveCount(0);
}
async function confirmDelete(page: Page, trigger: Locator, path: string) {
  await trigger.click();
  const [response] = await Promise.all([
    page.waitForResponse((result) => result.request().method() === "DELETE" && new URL(result.url()).pathname === path),
    confirmation(page).getByRole("button", { name: "Confirm", exact: true }).click(),
  ]);
  return response;
}

test("resource rename and delete cancel flows preserve data while confirmed deletion cascades keys and memberships", async ({ page }) => {
  const originalName = "Resource lifecycle application";
  const renamedName = "Renamed lifecycle application";
  const projectId = await createProject(page, originalName);
  const { create } = await api(page);
  const first = await create(`/projects/${projectId}/environments`, { name: "disposable-dev" });
  const second = await create(`/projects/${projectId}/environments`, { name: "retained-until-project-delete" });
  const firstKey = await create(`/projects/${projectId}/environments/${first.id}/keys`, { name: "Environment cascade key" });
  const secondKey = await create(`/projects/${projectId}/environments/${second.id}/keys`, { name: "Project cascade key" });
  const member = await create(`/projects/${projectId}/members`, { email: "resource-lifecycle-viewer@example.test", display_name: "Synthetic lifecycle viewer", role: "viewer", password: "Synthetic resource membership password" });
  const template = await create("/templates", { name: "Library survives project deletion", key: "resource-library-survives", channel: "email", project_ids: [projectId], draft });
  const scope = (key: string) => page.request.get("/api/v1/delivery/scope", { headers: { Authorization: `Bearer ${key}` } });
  expect((await scope(firstKey.key)).status()).toBe(200);
  expect((await scope(secondKey.key)).status()).toBe(200);
  await nav(page, "Projects").click();
  await rename(page, card(page, originalName).getByRole("button", { name: `Rename ${originalName}`, exact: true }), "Rename project", "Cancelled project name", false);
  await expect(card(page, originalName)).toBeVisible();
  expect((await (await page.request.get(`/api/v1/projects/${projectId}`)).json()).name).toBe(originalName);
  await rename(page, card(page, originalName).getByRole("button", { name: `Rename ${originalName}`, exact: true }), "Rename project", renamedName, true);
  await expect(card(page, renamedName)).toBeVisible();
  expect((await (await page.request.get(`/api/v1/projects/${projectId}`)).json()).name).toBe(renamedName);
  await page.goto(`/environments?project=${projectId}`);
  await rename(page, row(page, first.name).getByRole("button", { name: "Rename", exact: true }), "Rename environment", "cancelled-environment", false);
  await expect(row(page, first.name)).toBeVisible();
  expect((await (await page.request.get(`/api/v1/projects/${projectId}/environments/${first.id}`)).json()).name).toBe(first.name);
  const renamedEnvironment = "renamed-disposable-dev";
  await rename(page, row(page, first.name).getByRole("button", { name: "Rename", exact: true }), "Rename environment", renamedEnvironment, true);
  await expect(row(page, renamedEnvironment).getByText(renamedName, { exact: true })).toBeVisible();
  const environmentPath = `/api/v1/projects/${projectId}/environments/${first.id}`;
  expect((await (await page.request.get(environmentPath)).json()).name).toBe(renamedEnvironment);
  await cancelDelete(page, row(page, renamedEnvironment).getByRole("button", { name: "Delete", exact: true }), `Delete ${renamedEnvironment} and its API keys?`);
  expect((await scope(firstKey.key)).status()).toBe(200);
  expect((await page.request.get(environmentPath)).status()).toBe(200);
  expect((await confirmDelete(page, row(page, renamedEnvironment).getByRole("button", { name: "Delete", exact: true }), environmentPath)).status()).toBe(204);
  await expect(row(page, renamedEnvironment)).toHaveCount(0);
  expect((await page.request.get(environmentPath)).status()).toBe(404);
  expect((await scope(firstKey.key)).status()).toBe(401);
  expect(sql(`SELECT count(*) FROM delivery_keys WHERE id='${firstKey.id}'`)).toBe("0");
  await page.goto(`/api-keys?project=${projectId}&environment=${first.id}`);
  await expect(page.getByText("This environment is unavailable", { exact: true })).toBeVisible();
  await expect(page.getByText("No matching keys", { exact: true })).toBeVisible();
  await expect(page.getByText("Environment cascade key", { exact: true })).toHaveCount(0);
  await nav(page, "Projects").click();
  await cancelDelete(page, card(page, renamedName).getByRole("button", { name: "Delete", exact: true }), `Delete ${renamedName}, its environments, keys, and project memberships? Library templates remain available.`);
  expect((await scope(secondKey.key)).status()).toBe(200);
  expect((await page.request.get(`/api/v1/projects/${projectId}`)).status()).toBe(200);
  expect((await confirmDelete(page, card(page, renamedName).getByRole("button", { name: "Delete", exact: true }), `/api/v1/projects/${projectId}`)).status()).toBe(204);
  await expect(card(page, renamedName)).toHaveCount(0);
  expect((await page.request.get(`/api/v1/projects/${projectId}`)).status()).toBe(404);
  expect((await page.request.get(`/api/v1/projects/${projectId}/environments/${second.id}`)).status()).toBe(404);
  expect((await scope(secondKey.key)).status()).toBe(401);
  // Verify real PostgreSQL cascades, not just an empty filtered screen.
  expect(sql(`SELECT (SELECT count(*) FROM environments WHERE project_id='${projectId}'),(SELECT count(*) FROM delivery_keys WHERE id='${secondKey.id}'),(SELECT count(*) FROM memberships WHERE project_id='${projectId}'),(SELECT count(*) FROM template_projects WHERE project_id='${projectId}'),(SELECT count(*) FROM accounts WHERE id='${member.account_id}')`)).toBe("0|0|0|0|1");
  const survivingTemplate = await page.request.get(`/api/v1/templates/${template.id}`);
  expect(survivingTemplate.status()).toBe(200);
  expect((await survivingTemplate.json()).projects).toEqual([]);
  await page.goto(`/environments?project=${projectId}`);
  await expect(page.getByText("This project is unavailable. Choose another project using the filter.", { exact: true })).toBeVisible();
  await expect(page.getByText("No matching environments", { exact: true })).toBeVisible();
  await page.goto(`/templates/${template.id}`);
  await expect(page.getByRole("heading", { name: template.name, exact: true })).toBeVisible();
});

test("draft template deletion supports cancel and confirm while immutable history and provider-owned projects reject deletion", async ({ page }) => {
  const projectName = "Protected resource lifecycle";
  const projectId = await createProject(page, projectName);
  const { create, headers } = await api(page);
  const disposable = await create("/templates", { name: "Disposable lifecycle template", key: "resource-disposable-template", channel: "email", project_ids: [projectId], draft });
  const immutable = await create("/templates", { name: "Immutable lifecycle template", key: "resource-immutable-template", channel: "email", project_ids: [projectId], draft });
  const versionResponse = await page.request.post(`/api/v1/templates/${immutable.id}/publish`, { headers, data: { branch_id: immutable.branch_id, expected_revision: immutable.draft_revision } });
  expect(versionResponse.status(), await versionResponse.text()).toBe(201);
  const published = await versionResponse.json();
  const environment = await create(`/projects/${projectId}/environments`, { name: "protected-dev" });
  const key = await create(`/projects/${projectId}/environments/${environment.id}/keys`, { name: "Protected lifecycle key" });
  const provider = await create("/providers", { name: "Provider keeps lifecycle project", provider_type: "smtp", project_id: projectId, config: { host: "mailpit", port: 1025, tls: "none", sender: "resource-lifecycle@example.test" } });
  await page.goto(`/templates?project=${projectId}`);
  await cancelDelete(page, row(page, disposable.name).getByRole("button", { name: "Delete", exact: true }), `Delete ${disposable.name} from the shared library and disconnect it from all projects?`);
  expect((await page.request.get(`/api/v1/templates/${disposable.id}`)).status()).toBe(200);
  expect((await confirmDelete(page, row(page, disposable.name).getByRole("button", { name: "Delete", exact: true }), `/api/v1/templates/${disposable.id}`)).status()).toBe(204);
  await expect(row(page, disposable.name)).toHaveCount(0);
  expect((await page.request.get(`/api/v1/templates/${disposable.id}`)).status()).toBe(404);
  await expect(row(page, immutable.name).getByRole("button", { name: "Delete", exact: true })).toHaveCount(0);
  const forbidden = await page.request.delete(`/api/v1/templates/${immutable.id}`, { headers });
  expect(forbidden.status()).toBe(409);
  expect(await forbidden.json()).toEqual({ detail: "Published templates retain immutable history and cannot be deleted" });
  const versions = await (await page.request.get(`/api/v1/templates/${immutable.id}/versions`)).json();
  expect(versions.map((version: { id: string }) => version.id)).toContain(published.id);
  await page.goto(`/templates/${disposable.id}`);
  await expect(page.getByRole("alert").filter({ hasText: "Template not found" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Email subject", exact: true })).toHaveCount(0);
  await nav(page, "Projects").click();
  const rejected = await confirmDelete(page, card(page, projectName).getByRole("button", { name: "Delete", exact: true }), `/api/v1/projects/${projectId}`);
  expect(rejected.status()).toBe(409);
  expect(await rejected.json()).toEqual({ detail: "A conflicting record already exists" });
  await expect(page.getByText("A conflicting record already exists", { exact: true })).toBeVisible();
  await expect(card(page, projectName)).toBeVisible();
  expect((await page.request.get(`/api/v1/projects/${projectId}/environments/${environment.id}`)).status()).toBe(200);
  expect((await page.request.get("/api/v1/delivery/scope", { headers: { Authorization: `Bearer ${key.key}` } })).status()).toBe(200);
  const retainedProviders = await (await page.request.get("/api/v1/providers")).json();
  expect(retainedProviders.map((item: { id: string }) => item.id)).toContain(provider.id);
  expect((await page.request.get(`/api/v1/templates/${immutable.id}`)).status()).toBe(200);
  expect(sql(`SELECT (SELECT count(*) FROM projects WHERE id='${projectId}'),(SELECT count(*) FROM delivery_keys WHERE id='${key.id}'),(SELECT count(*) FROM template_versions WHERE id='${published.id}')`)).toBe("1|1|1");
});
