import { expect, test } from "@playwright/test";
import { chooseOption, compose, createProject, createTemplate, editCode, setup } from "./support/compose";

setup();

test("shares an email layout, preserves draft edits and pins accepted deliveries across rollout and rollback", async ({ page }) => {
  const project = await createProject(page, "Layout lifecycle");
  const session = await (await page.request.get("/api/v1/auth/session")).json();
  const headers = { "X-CSRF-Token": session.csrf_token };
  async function write(method: "post" | "put", path: string, data: object) {
    const response = await page.request[method]("/api/v1" + path, { headers, data });
    expect(response.ok(), path).toBeTruthy();
    return response.json();
  }
  const post = (path: string, data: object) => write("post", path, data);
  const get = async (path: string) => {
    const response = await page.request.get("/api/v1" + path);
    expect(response.ok(), path).toBeTruthy();
    return response.json();
  };
  const env = await post(`/projects/${project}/environments`, { name: "layout-dev" });
  const target = { scope: "environment", project_id: project, environment_id: env.id, locale: "en" };
  const slot = "<!-- voxriva:body -->";
  const shell = (edition: string) => ({
    html: `<header><h1>${edition} · {{ brand }}</h1></header><main>${slot}</main><footer>Shared footer</footer>`,
    variable_schema: { type: "object", properties: { brand: { type: "string" } }, required: ["brand"], additionalProperties: false },
    runtime_defaults: { brand: "Preview Market" },
  });
  const layout = await post("/templates", { name: "Market shell", key: "market-shell", channel: "email", is_layout: true, project_ids: [project], draft: shell("Day") });
  const layoutPath = `/templates/${layout.id}`;
  const publish = (path: string, branch: string, revision: number) => post(path + "/publish", {
    branch_id: branch, expected_revision: revision, project_id: project, environment_id: env.id,
  });
  const deploy = (path: string, version: string, generation: number, action = "deploy") =>
    post(path + "/deployments/" + action, { ...target, version_id: version, expected_generation: generation });
  const day = await publish(layoutPath, layout.branch_id, 1);
  await deploy(layoutPath, day.id, 0);
  await write("put", layoutPath + "/draft", { expected_revision: 1, draft: shell("Night") });
  const night = await publish(layoutPath, layout.branch_id, 2);

  const letters = [
    { name: "Layout welcome", subject: "Layout welcome subject", body: "Welcome, new customer", pinned: false },
    { name: "Layout receipt", subject: "Layout receipt subject", body: "Here is your receipt", pinned: true },
  ];
  const prepared = [];
  for (const letter of letters) {
    const id = await createTemplate(page, letter.name);
    const path = `/templates/${id}`;
    await page.getByLabel("Email layout", { exact: true }).selectOption(layout.id);
    if (letter.pinned) await page.getByLabel("Layout version", { exact: true }).selectOption(day.id);
    await editCode(page, "Email subject", letter.subject);
    await editCode(page, "Email HTML", `<p>${letter.body}</p>`);
    const preview = page.frameLocator('iframe[title="Email HTML preview"]');
    await expect(preview.getByText("Day · Preview Market")).toBeVisible();
    await expect(preview.getByText(letter.body)).toBeVisible();
    await page.getByRole("button", { name: "Save draft", exact: true }).click();
    await expect(page.getByText("Draft saved.", { exact: true })).toBeVisible();
    const saved = await get(path);
    const published = await publish(path, saved.branch_id, saved.draft_revision);
    await deploy(path, published.id, 0);
    prepared.push({ ...letter, key: saved.key, path, versionId: published.id });
  }
  const [active, fixed] = prepared;
  await page.goto(active.path);
  await editCode(page, "Email subject", "Unsaved welcome");
  const versionPicker = page.getByRole("combobox", { name: "Template version", exact: true });
  await expect(page.getByRole("combobox", { name: "Editing language", exact: true })).toBeVisible();
  await chooseOption(page, versionPicker, "main · v1");
  await expect(page.getByText("Viewing published · main · v1")).toBeVisible();
  await expect(page.getByRole("tab", { name: "Draft editor" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: active.subject })).toBeVisible();
  await chooseOption(page, versionPicker, "Current draft");
  await expect(page.getByRole("textbox", { name: "Email subject" })).toHaveValue("Unsaved welcome");
  const activeMode = page.getByLabel("Layout version", { exact: true });
  await expect(activeMode.locator("option:checked")).toHaveText("Active in environment");
  expect((await get(active.path)).draft.subject).toBe(active.subject);

  const provider = await post("/providers", { name: "Layout SMTP", provider_type: "smtp", project_id: project, config: { host: "mailpit", port: 1025, tls: "none", sender: "layout@example.test" } });
  await write("put", "/providers/bindings", { ...target, channel: "email", expected_generation: 0, revision_id: provider.latest.id });
  const key = await post(`/projects/${project}/environments/${env.id}/keys`, { name: "Layout lifecycle key" });
  const deliveries: { id: string; edition: string; recipient: string; subject: string; body: string }[] = [];
  async function send(letter: typeof active, stage: string, edition: string) {
    const recipient = `${letter.key}-${stage}@example.test`;
    const response = await page.request.post("/api/v1/notifications", {
      headers: { Authorization: `Bearer ${key.key}`, "Idempotency-Key": stage + "-" + letter.key },
      data: { template_key: letter.key, recipient, context: { brand: "Delivery Market" } },
    });
    expect(response.status(), await response.text()).toBe(202);
    const accepted = await response.json();
    expect(accepted.template_version_id).toBe(letter.versionId);
    deliveries.push({ id: accepted.id, edition, recipient, subject: letter.subject, body: letter.body });
    return accepted.id;
  }

  compose("stop", "email-worker");
  try {
    const queued = await send(active, "before-rollout", "Day");
    expect((await get("/notifications/" + queued)).status).toBe("queued");
    await deploy(layoutPath, night.id, 1);
    await send(active, "after-rollout", "Night");
    await send(fixed, "after-rollout", "Day");
    await deploy(layoutPath, day.id, 2, "rollback");
    await send(active, "after-rollback", "Day");
  } finally {
    compose("start", "email-worker");
  }

  for (const entry of deliveries) {
    await expect.poll(async () => (await get("/notifications/" + entry.id)).status, { timeout: 40_000 }).toBe("sent");
  }
  const mailpit = `http://127.0.0.1:${process.env.VOXRIVA_MAILPIT_PORT}`;
  const inbox = await (await page.request.get(mailpit + "/api/v1/messages")).json();
  for (const entry of deliveries) {
    const message = inbox.messages.find((message: { To: { Address: string }[] }) => message.To.some(({ Address }) => Address === entry.recipient));
    expect(message?.Subject, entry.recipient).toBe(entry.subject);
    const delivered = await (await page.request.get(mailpit + "/api/v1/message/" + message.ID)).json();
    expect(delivered.HTML).toContain(entry.edition + " · Delivery Market");
    expect(delivered.HTML).toContain(entry.body);
    expect(delivered.HTML).toContain("Shared footer");
  }
});
