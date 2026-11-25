import { expect, test } from "@playwright/test";
import { compose, nav, setup } from "./support/compose";

setup();

test("delivers a real API notification through the outbox and Celery with pinned revisions and history", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const csrf = { "X-CSRF-Token": (await (await page.request.get("/api/v1/auth/session")).json()).csrf_token };
  const project = await (await page.request.post("/api/v1/projects", { headers: csrf, data: { name: "Real delivery demo" } })).json();
  const env = await (await page.request.post(`/api/v1/projects/${project.id}/environments`, { headers: csrf, data: { name: "dev" } })).json();
  const draft = { subject: "Original {{ name }}", html: "<h1>Hello {{ name }}</h1>", text: "Hello {{ name }}", variable_schema: { type: "object", properties: { name: { type: "string" } }, required: ["name"], additionalProperties: false }, preview_context: { name: "PREVIEW_FIXTURE_ONLY" } };
  const template = await (await page.request.post("/api/v1/templates", { headers: csrf, data: { name: "First real welcome", key: "first-real-welcome", channel: "email", project_ids: [project.id], draft } })).json();
  const base = `/api/v1/templates/${template.id}`;
  const version = await (await page.request.post(`${base}/publish`, { headers: csrf, data: { branch_id: template.branch_id, expected_revision: 1 } })).json();
  const target = { scope: "environment", project_id: project.id, environment_id: env.id, locale: "en" };
  expect((await page.request.post(`${base}/deployments/deploy`, { headers: csrf, data: { ...target, expected_generation: 0, version_id: version.id } })).status()).toBe(200);
  const provider = await (await page.request.post("/api/v1/providers", { headers: csrf, data: { name: "Original SMTP", provider_type: "smtp", project_id: project.id, config: { host: "mailpit", port: 1025, tls: "none", sender: "original.sender@example.test" } } })).json();
  expect((await page.request.put("/api/v1/providers/bindings", { headers: csrf, data: { ...target, channel: "email", expected_generation: 0, revision_id: provider.latest.id } })).status()).toBe(200);
  const keyPath = `/api/v1/projects/${project.id}/environments/${env.id}/keys`;
  const key = await (await page.request.post(keyPath, { headers: csrf, data: { name: "Real integration" } })).json();
  const delivery = { Authorization: `Bearer ${key.key}`, "Idempotency-Key": "real-notification-1" };
  const input = { template_key: template.key, recipient: "synthetic.recipient@example.test", context: { name: "RUNTIME_PERSON" } };
  const mailbox = async () => JSON.parse(compose("exec", "-T", "api", "python", "-c", "import urllib.request; print(urllib.request.urlopen('http://mailpit:8025/api/v1/messages').read().decode())"));
  const before = (await mailbox()).total;
  compose("stop", "email-worker");
  try {
    const invalid = await page.request.post("/api/v1/notifications", { headers: delivery, data: { ...input, context: {} } });
    expect(invalid.status()).toBe(422);
    const responses = await Promise.all([1, 2].map(() => page.request.post("/api/v1/notifications", { headers: delivery, data: input })));
    expect(responses.map((response) => response.status())).toEqual([202, 202]);
    const accepted = await responses[0].json();
    expect((await responses[1].json()).id).toBe(accepted.id);
    expect(accepted.template_version_id).toBe(version.id); expect(accepted.provider_revision_id).toBe(provider.latest.id);
    expect((await page.request.post("/api/v1/notifications", { headers: delivery, data: { ...input, context: { name: "DIFFERENT" } } })).status()).toBe(409);
    await page.goto("/notifications");
    const row = page.getByRole("row").filter({ hasText: "First real welcome" });
    await expect(row.getByText("Queued", { exact: true })).toBeVisible();
    await expect(row.getByText(input.recipient, { exact: true })).toBeVisible();
    await page.getByRole("searchbox", { name: "Search recipient email", exact: true }).fill("SYNTHETIC.RECIPIENT");
    await page.getByRole("searchbox", { name: "Search recipient email", exact: true }).press("Enter");
    await expect(row.getByText(input.recipient, { exact: true })).toBeVisible();
    const deliveryView = await (await page.request.get(accepted.status_url, { headers: { Authorization: delivery.Authorization } })).json();
    expect(deliveryView.recipient_mask).toBe("s***@***");
    expect(deliveryView.recipient_email).toBeNull();
    expect(JSON.stringify(deliveryView)).not.toContain(input.recipient);
    await page.screenshot({ path: test.info().outputPath("notifications-queued.png"), fullPage: true, animations: "disabled" });
    expect((await mailbox()).total).toBe(before);
    const changed = { ...draft, subject: "Changed {{ name }}" };
    expect((await page.request.put(`${base}/draft`, { headers: csrf, data: { expected_revision: 1, draft: changed } })).status()).toBe(200);
    const v2 = await (await page.request.post(`${base}/publish`, { headers: csrf, data: { branch_id: template.branch_id, expected_revision: 2 } })).json();
    expect((await page.request.post(`${base}/deployments/deploy`, { headers: csrf, data: { ...target, expected_generation: 1, version_id: v2.id } })).status()).toBe(200);
    const p2 = await (await page.request.post(`/api/v1/providers/${provider.id}/revisions`, { headers: csrf, data: { expected_revision: 1, config: { sender: "new.sender@example.test" } } })).json();
    expect((await page.request.put("/api/v1/providers/bindings", { headers: csrf, data: { ...target, channel: "email", expected_generation: 1, revision_id: p2.latest.id } })).status()).toBe(200);
    compose("start", "email-worker");
    await expect.poll(async () => (await (await page.request.get(accepted.status_url, { headers: { Authorization: delivery.Authorization } })).json()).status, { timeout: 30000 }).toBe("sent");
    await expect.poll(async () => (await mailbox()).total).toBe(before + 1);
    const message = (await mailbox()).messages.find((item: { Subject: string }) => item.Subject === "Original RUNTIME_PERSON");
    expect(message).toBeTruthy(); expect(message.From.Address).toBe("original.sender@example.test");
    const again = await (await page.request.post("/api/v1/notifications", { headers: delivery, data: input })).json();
    expect(again.id).toBe(accepted.id); expect(again.replayed).toBe(true); expect(again.status).toBe("sent");
    await row.getByRole("link", { name: "View delivery", exact: true }).click(); await page.reload();
    await expect(page.getByRole("heading", { name: "Delivery details", exact: true })).toBeVisible();
    await expect(page.getByText("Original SMTP · r1", { exact: true })).toBeVisible();
    await expect(page.getByText("main · v1 · en", { exact: true })).toBeVisible();
    await expect(page.getByText("Provider accepted the message", { exact: true })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath("notification-details.png"), fullPage: true, animations: "disabled" });
    const attempts = await (await page.request.get(accepted.status_url)).json();
    expect(attempts.attempts).toHaveLength(1); expect(JSON.stringify(attempts)).not.toContain("RUNTIME_PERSON");
    const persisted = compose("exec", "-T", "postgres", "psql", "-U", "voxriva", "-d", "voxriva", "-Atc", `SELECT count(*),count(encrypted_payload) FROM notifications WHERE id='${accepted.id}'`);
    expect(persisted.trim()).toBe("1|0");
    expect((await mailbox()).total).toBe(before + 1);
  } finally { compose("start", "email-worker"); }
});

test("recovers a broker outage and replays a failed notification from delivery health", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const csrf = { "X-CSRF-Token": (await (await page.request.get("/api/v1/auth/session")).json()).csrf_token };
  async function post(path: string, data: object) { const result = await page.request.post(`/api/v1${path}`, { headers: csrf, data }); expect(result.ok(), await result.text()).toBeTruthy(); return result.json(); }
  const project = await post("/projects", { name: "Recovery demo" });
  const env = await post(`/projects/${project.id}/environments`, { name: "dev" });
  const template = await post("/templates", { name: "Recovery welcome", key: "recovery-welcome", channel: "email", project_ids: [project.id], draft: { subject: "Recovery {{ name }}", text: "Hello {{ name }}", html: "", variable_schema: { type: "object", properties: { name: { type: "string" } }, required: ["name"] }, preview_context: { name: "Preview only" } } });
  const version = await post(`/templates/${template.id}/publish`, { branch_id: template.branch_id, expected_revision: 1 });
  const target = { scope: "environment", project_id: project.id, environment_id: env.id };
  await post(`/templates/${template.id}/deployments/deploy`, { ...target, locale: "en", expected_generation: 0, version_id: version.id });
  const provider = await post("/providers", { name: "Recovery SMTP", provider_type: "smtp", project_id: project.id, config: { host: "mailpit", port: 1, tls: "none", sender: "recovery@example.test", timeout: 1 } });
  expect((await page.request.put("/api/v1/providers/bindings", { headers: csrf, data: { ...target, channel: "email", expected_generation: 0, revision_id: provider.latest.id } })).status()).toBe(200);
  const key = await post(`/projects/${project.id}/environments/${env.id}/keys`, { name: "Recovery test" });
  let identifier = "";
  compose("stop", "redis");
  try {
    const accepted = await page.request.post("/api/v1/notifications", { headers: { Authorization: `Bearer ${key.key}`, "Idempotency-Key": "broker-offline" }, data: { template_key: template.key, recipient: "synthetic.recovery@example.test", context: { name: "Runtime recovery" } } });
    expect(accepted.status()).toBe(202); identifier = (await accepted.json()).id;
    await page.goto(`/notifications/${identifier}`);
    await expect(page.getByText("Queued", { exact: true })).toBeVisible();
    expect((await (await page.request.get(`/api/v1/notifications/${identifier}`)).json()).attempts).toHaveLength(0);
  } finally { compose("start", "redis"); }
  await expect.poll(async () => (await (await page.request.get(`/api/v1/notifications/${identifier}`)).json()).status, { timeout: 45000 }).toBe("failed");
  const failed = await (await page.request.get(`/api/v1/notifications/${identifier}`)).json();
  expect(failed.attempts).toHaveLength(3); expect(failed.payload_available).toBe(true);
  const fixed = await post(`/providers/${provider.id}/revisions`, { expected_revision: 1, config: { port: 1025 } });
  expect((await page.request.put("/api/v1/providers/bindings", { headers: csrf, data: { ...target, channel: "email", expected_generation: 1, revision_id: fixed.latest.id } })).status()).toBe(200);
  await page.reload();
  await page.getByRole("button", { name: "Replay failed notification", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Use current template and provider deployments").check();
  await dialog.getByRole("button", { name: "Confirm replay", exact: true }).click();
  await expect(page).not.toHaveURL(new RegExp(identifier));
  await expect(page.getByText("Sent", { exact: true }).first()).toBeVisible({ timeout: 30000 });
  await expect(page.getByText("Recovery SMTP · r2", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "the original delivery", exact: true })).toHaveAttribute("href", `/notifications/${identifier}?returnTo=${encodeURIComponent("/notifications")}`);
  await page.screenshot({ path: test.info().outputPath("recovery-replayed.png"), fullPage: true, animations: "disabled" });
  await nav(page, "Operations").click();
  await expect(page.getByRole("heading", { name: "Operations", exact: true })).toBeVisible();
  await expect(page.getByText("Broker: ready", { exact: false })).toBeVisible();
  for (const worker of ["email@", "push@"]) {
    await expect(page.getByRole("row").filter({ hasText: worker }).getByText("online", { exact: true })).toBeVisible({ timeout: 15000 });
  }
  await expect(page.getByRole("row").filter({ hasText: "task-succeeded" }).first()).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("delivery-health.png"), fullPage: true, animations: "disabled" });
  await page.getByRole("tab", { name: "Audit log", exact: true }).click();
  const auditEvent = page.getByRole("row").filter({ hasText: "Failed notification replayed" }).first();
  await expect(auditEvent).toBeVisible();
  await auditEvent.getByText("Technical details", { exact: true }).click();
  await expect(auditEvent.getByText("notification.replay", { exact: true })).toBeVisible();
  const metrics = await page.request.get("/api/v1/operations/metrics");
  expect(metrics.status()).toBe(200); expect(await metrics.text()).toContain('voxriva_notifications{status="sent"}');
  expect(compose("exec", "-T", "postgres", "psql", "-U", "voxriva", "-d", "voxriva", "-Atc", `SELECT status,attempt_count FROM notifications WHERE id='${identifier}'`).trim()).toBe("failed|3");
});
