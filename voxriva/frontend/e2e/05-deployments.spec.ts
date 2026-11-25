import { expect, test } from "@playwright/test";
import { createProject, createTemplate, editCode, nav, setup, setVariables } from "./support/compose";

setup();

test("publishes immutable versions, forks branches, deploys and rolls back with concurrency protection", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const projectId = await createProject(page, "Release demo");
  async function environment(name: string) {
    await nav(page, "Environments").click();
    await page.getByRole("button", { name: "Create environment", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Name", { exact: true }).fill(name);
    await dialog.getByLabel("Project", { exact: true }).fill("Release demo");
    await page.locator(".ant-select-dropdown:visible").getByText("Release demo", { exact: true }).click();
    await dialog.getByRole("button", { name: "Create environment", exact: true }).click();
    await expect(dialog).toHaveCount(0);
  }
  await environment("dev"); await environment("prod");
  const templateId = await createTemplate(page, "Release welcome");
  const base = `/api/v1/templates/${templateId}`;
  const csrf = (await (await page.request.get("/api/v1/auth/session")).json()).csrf_token;
  const headers = { "X-CSRF-Token": csrf };
  async function save() {
    // AntD's decorative spinner can remain in the accessible name when its
    // exit animation was interrupted by switching tabs. Readiness comes from
    // the actual loading state and this save's response, not a previous alert.
    const button = page.getByRole("button", { name: /^(?:loading )?Save draft$/ });
    await expect(button).not.toHaveClass(/\bant-btn-loading\b/);
    await expect(button).toBeEnabled();
    const [response] = await Promise.all([
      page.waitForResponse((result) => result.request().method() === "PUT" && result.url() === new URL(`${base}/draft`, page.url()).href),
      button.click(),
    ]);
    expect(response.ok(), await response.text()).toBeTruthy();
    const saved = await response.json();
    await expect(page.getByText(`Revision ${saved.draft_revision} · Manual save · Ctrl / ⌘ S`, { exact: true })).toBeVisible();
    await expect(button).not.toHaveClass(/\bant-btn-loading\b/);
    await expect(page.getByText("Saved draft", { exact: true })).toBeVisible();
    await expect(page.getByText("Draft saved.", { exact: true })).toBeVisible();
  }
  async function publishVersion(note: string) {
    await page.getByRole("button", { name: "Publish version", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Publication note", { exact: true }).fill(note);
    await dialog.getByRole("button", { name: "Publish version", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Published versions", exact: true })).toBeVisible();
  }
  async function selectOption(field: string, value: string) {
    await page.getByRole("dialog").getByRole("combobox", { name: field, exact: true }).press("ArrowDown");
    await page.locator(".ant-select-dropdown:visible").getByText(value, { exact: true }).last().click();
  }
  const matrixRow = (name: string) => page.getByRole("row").filter({ hasText: `Release demo / ${name}` });
  await editCode(page, "Email subject", "Release one {{ name }}");
  await editCode(page, "Email HTML", "<h1>Hello {{ name }}!</h1>");
  await setVariables(page); await save(); await publishVersion("First stable release");
  let versions = await (await page.request.get(`${base}/versions`)).json();
  const v1 = versions.find((version: { branch_name: string; number: number }) => version.branch_name === "main" && version.number === 1);
  let matrix = await (await page.request.get(`${base}/deployments`)).json();
  expect(matrix.rows.every((row: { effective_version: unknown }) => row.effective_version === null)).toBe(true);
  await page.getByRole("tab", { name: "Deployments", exact: true }).click();
  await matrixRow("prod").getByRole("button", { name: "Deploy", exact: true }).click();
  let dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Release demo / prod", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Deploy", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(matrixRow("prod").getByText("English · en · main · v1", { exact: true }).first()).toBeVisible();
  await page.getByRole("tab", { name: "Draft editor", exact: true }).click();
  await editCode(page, "Email subject", "Release two {{ name }}");
  await save(); await publishVersion("Second stable release");
  versions = await (await page.request.get(`${base}/versions`)).json();
  const v2 = versions.find((version: { branch_name: string; number: number }) => version.branch_name === "main" && version.number === 2);
  matrix = await (await page.request.get(`${base}/deployments`)).json();
  expect(matrix.rows.find((row: { environment_name: string }) => row.environment_name === "prod").version.id).toBe(v1.id);
  await page.getByText("Advanced: branches", { exact: true }).click();
  await page.getByRole("button", { name: "Create branch", exact: true }).click();
  dialog = page.getByRole("dialog");
  await selectOption("Published source", "English · en · main · v1");
  await dialog.getByLabel("Branch name", { exact: true }).fill("candidate");
  await dialog.getByRole("button", { name: "Create branch", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "Draft editor", exact: true })).toHaveAttribute("aria-selected", "true");
  const branchId = new URL(page.url()).searchParams.get("branch")!;
  expect((await (await page.request.get(`${base}?branch_id=${branchId}`)).json()).draft.subject).toBe("Release one {{ name }}");
  await editCode(page, "Email subject", "Candidate {{ name }}"); await save(); await publishVersion("Independent candidate");
  versions = await (await page.request.get(`${base}/versions`)).json();
  expect(versions.find((version: { branch_name: string }) => version.branch_name === "candidate").parent_version_id).toBe(v1.id);
  expect((await (await page.request.get(base)).json()).draft.subject).toBe("Release two {{ name }}");
  await page.getByText("Advanced: branches", { exact: true }).click();
  await page.getByRole("combobox", { name: "Editing branch", exact: true }).press("ArrowDown");
  await page.locator(".ant-select-dropdown:visible").getByText("main · v2", { exact: true }).last().click();
  await page.getByRole("tab", { name: "Deployments", exact: true }).click();
  await matrixRow("dev").getByRole("button", { name: "Deploy", exact: true }).click();
  await selectOption("Published version", "English · en · main · v2");
  dialog = page.getByRole("dialog"); await dialog.getByRole("button", { name: "Deploy", exact: true }).click(); await expect(dialog).toHaveCount(0);
  await expect(matrixRow("dev").getByText("English · en · main · v2", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Promote", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Use inheritance", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Clear default", exact: true })).toHaveCount(0);
  await matrixRow("prod").getByRole("button", { name: "Deploy", exact: true }).click();
  await selectOption("Published version", "English · en · main · v2");
  dialog = page.getByRole("dialog");
  await expect(dialog.getByText("No incompatible variable-contract changes detected", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Deploy", exact: true }).click(); await expect(dialog).toHaveCount(0);
  await expect(matrixRow("prod").getByText("English · en · main · v2", { exact: true }).first()).toBeVisible();
  await matrixRow("prod").getByRole("button", { name: "Roll back", exact: true }).click();
  dialog = page.getByRole("dialog"); await expect(dialog.getByRole("button", { name: "Roll back", exact: true })).toBeEnabled();
  await dialog.getByRole("button", { name: "Roll back", exact: true }).click(); await expect(dialog).toHaveCount(0);
  await expect(matrixRow("prod").getByText("English · en · main · v1", { exact: true }).first()).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("deployment-matrix.png"), fullPage: true, animations: "disabled" });
  await matrixRow("prod").getByRole("button", { name: "Activity", exact: true }).click();
  dialog = page.getByRole("dialog"); await expect(dialog.getByText("Deploy", { exact: true }).first()).toBeVisible();
  await expect(dialog.getByText("Roll back", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Close activity", exact: true }).click();
  await page.getByRole("tab", { name: "Version history", exact: true }).click();
  const original = page.getByRole("row").filter({ has: page.locator(".version-identity > strong").filter({ hasText: /^English · en · main · v1$/ }) });
  await original.getByRole("button", { name: "Preview", exact: true }).click();
  dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "Release one Taylor Synthetic", exact: true })).toBeVisible();
  await dialog.getByRole("textbox", { name: "Published preview variables", exact: true }).fill('{"name":"Snapshot Check"}');
  await expect(dialog.getByRole("heading", { name: "Release one Snapshot Check", exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Close preview", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Original version", exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Variable schema", exact: true }).click();
  await expect(page.locator(".monaco-diff-editor:visible")).toHaveCount(1);
  await page.screenshot({ path: test.info().outputPath("version-history.png"), fullPage: true, animations: "disabled" });
  const env = await (await page.request.post(`/api/v1/projects/${projectId}/environments`, { headers, data: { name: "concurrent" } })).json();
  const input = { scope: "environment", project_id: projectId, environment_id: env.id, locale: "en", expected_generation: 0, expected_effective_version_id: null };
  const competing = await Promise.all([v1, v2].map((version) => page.request.post(`${base}/deployments/deploy`, { headers, data: { ...input, version_id: version.id } })));
  expect(competing.map((response) => response.status()).sort()).toEqual([200, 409]);
  const final = (await (await page.request.get(`${base}/deployments`)).json()).rows.find((row: { environment_id: string }) => row.environment_id === env.id);
  expect(final.generation).toBe(1); expect(final.history).toHaveLength(1);
  await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "Deployments", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Deployments", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Deployments", exact: true })).toBeVisible();
  await page.getByRole("searchbox", { name: "Search deployments", exact: true }).fill("release-welcome");
  await page.getByRole("combobox", { name: "Filter scope", exact: true }).click();
  await page.locator(".ant-select-dropdown:visible").getByText("Environments", { exact: true }).click();
  const overviewRows = page.getByRole("row").filter({ hasText: "release-welcome" });
  await expect(overviewRows).toHaveCount(3);
  await expect(overviewRows.filter({ hasText: "prod" }).getByText("main · v1 · en", { exact: true })).toBeVisible();
  await expect(overviewRows.filter({ hasText: "dev" }).getByText("main · v2 · en", { exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Filter channel", exact: true }).click();
  await page.locator(".ant-select-dropdown:visible").getByText("Push", { exact: true }).click();
  await expect(page.getByText("No deployments match these filters", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Reset filters", exact: true }).click();
  await page.getByRole("searchbox", { name: "Search deployments", exact: true }).fill("release-welcome");
  await page.screenshot({ path: test.info().outputPath("deployments-overview.png"), fullPage: true, animations: "disabled" });
  await page.getByRole("row").filter({ hasText: "release-welcome" }).filter({ hasText: "prod" }).getByRole("link", { name: "Open matrix", exact: true }).click();
  await expect(page.getByRole("tab", { name: "Deployments", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(matrixRow("prod").getByText("English · en · main · v1", { exact: true }).first()).toBeVisible();
});

test("deployment dialogs require acknowledgement of incompatible variable contracts", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const project = await createProject(page, "Contract demo");
  const headers = { "X-CSRF-Token": (await (await page.request.get("/api/v1/auth/session")).json()).csrf_token };
  const env = await (await page.request.post(`/api/v1/projects/${project}/environments`, { headers, data: { name: "production" } })).json();
  const content = { subject: "Contract {{ name }}", html: "<p>{{ name }}</p>", variable_schema: { type: "object", properties: { name: { type: "string" } }, required: ["name"], additionalProperties: false }, preview_context: { name: "Synthetic Example" } };
  const item = await (await page.request.post("/api/v1/templates", { headers, data: { name: "Contract welcome", key: "contract-welcome", channel: "email", project_ids: [project], draft: content } })).json();
  const base = `/api/v1/templates/${item.id}`;
  const v1 = await (await page.request.post(`${base}/publish`, { headers, data: { branch_id: item.branch_id, expected_revision: 1 } })).json();
  const target = { scope: "environment", project_id: project, environment_id: env.id, locale: "en" };
  expect((await page.request.post(`${base}/deployments/deploy`, { headers, data: { ...target, version_id: v1.id, expected_generation: 0 } })).status()).toBe(200);
  const next = { ...content, variable_schema: { ...content.variable_schema, properties: { ...content.variable_schema.properties, code: { type: "string" } }, required: ["name", "code"] }, preview_context: { name: "Synthetic Example", code: "EXAMPLE" } };
  expect((await page.request.put(`${base}/draft`, { headers, data: { draft: next, expected_revision: 1 } })).status()).toBe(200);
  const v2 = await (await page.request.post(`${base}/publish`, { headers, data: { branch_id: item.branch_id, expected_revision: 2 } })).json();
  expect(v2.number).toBe(2);
  await page.goto(`/templates/${item.id}`);
  await page.getByRole("tab", { name: "Deployments", exact: true }).click();
  const row = page.getByRole("row").filter({ hasText: "Contract demo / production" });
  await row.getByRole("button", { name: "Deploy", exact: true }).click();
  let dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Variable-contract changes need review", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Deploy", exact: true })).toBeDisabled();
  await expect(dialog).toHaveCSS("transform", "none");
  await page.screenshot({ path: test.info().outputPath("schema-change-confirmation.png"), fullPage: true, animations: "disabled" });
  await dialog.getByRole("checkbox", { name: "I acknowledge the variable-contract changes shown above.", exact: true }).check();
  await dialog.getByRole("button", { name: "Deploy", exact: true }).click(); await expect(dialog).toHaveCount(0);
  await expect(row.getByText("English · en · main · v2", { exact: true }).first()).toBeVisible();
  await row.getByRole("button", { name: "Roll back", exact: true }).click(); dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("button", { name: "Roll back", exact: true })).toBeDisabled();
  await dialog.getByRole("checkbox", { name: "I acknowledge the variable-contract changes shown above.", exact: true }).check();
  await dialog.getByRole("button", { name: "Roll back", exact: true }).click(); await expect(dialog).toHaveCount(0);
  await expect(row.getByText("English · en · main · v1", { exact: true }).first()).toBeVisible();
});
