import { expect, test } from "@playwright/test";
import { chooseOption, compose, createProject, nav, setup } from "./support/compose";

setup();

test("configures SMTP, tests without sending, sends to the local inbox and pins provider revisions", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const projectId = await createProject(page, "SMTP demo");
  const headers = { "X-CSRF-Token": (await (await page.request.get("/api/v1/auth/session")).json()).csrf_token };
  const env = await (await page.request.post(`/api/v1/projects/${projectId}/environments`, { headers, data: { name: "smtp-dev" } })).json();
  const inbox = async () => JSON.parse(compose("exec", "-T", "api", "python", "-c", "import urllib.request; print(urllib.request.urlopen('http://mailpit:8025/api/v1/messages').read().decode())"));
  const before = (await inbox()).total;
  await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "Providers", exact: true }).click();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Providers", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Add provider", exact: true }).click();
  let dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name", { exact: true }).fill("Local SMTP demo");
  const select = async (label: string, text: string) => {
    await chooseOption(page, dialog.getByLabel(label, { exact: true }), text);
  };
  await select("Owner", "SMTP demo");
  await dialog.getByLabel("SMTP host", { exact: true }).fill("mailpit");
  await dialog.getByLabel("Port", { exact: true }).fill("1025");
  await select("Transport security", "none");
  await dialog.getByLabel("Sender email", { exact: true }).fill("sender@example.test");
  await page.screenshot({ path: test.info().outputPath("provider-configuration.png"), fullPage: true, animations: "disabled" });
  await dialog.getByRole("button", { name: "Create provider", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  const row = page.getByRole("row").filter({ hasText: "Local SMTP demo" });
  await row.getByRole("button", { name: "Test connection", exact: true }).click();
  await expect(page.getByText(/SMTP connection and configured authentication succeeded/)).toBeVisible();
  expect((await inbox()).total).toBe(before);
  await row.getByRole("button", { name: "Send test email", exact: true }).click(); dialog = page.getByRole("dialog");
  await dialog.getByLabel("Recipient email", { exact: true }).fill("synthetic.smtp@example.test");
  await dialog.getByLabel("Subject", { exact: true }).fill("Voxriva provider smoke test");
  await dialog.getByLabel("Message", { exact: true }).fill("Synthetic local email from the Providers screen.");
  await dialog.getByRole("button", { name: "Send test email", exact: true }).click(); await expect(dialog).toHaveCount(0);
  await expect.poll(async () => (await inbox()).total).toBe(before + 1);
  const messages = (await inbox()).messages;
  expect(messages.some((message: { Subject: string }) => message.Subject === "Voxriva provider smoke test")).toBe(true);
  const all = await (await page.request.get("/api/v1/providers")).json();
  const item = all.find((value: { name: string }) => value.name === "Local SMTP demo");
  await page.getByRole("tab", { name: "Channel bindings", exact: true }).click();
  await page.getByRole("searchbox", { name: "Search provider bindings", exact: true }).fill("SMTP demo / smtp-dev");
  const binding = page.getByRole("row").filter({ hasText: "SMTP demo / smtp-dev" }).filter({ hasText: "Email" });
  await binding.getByRole("button", { name: "Assign provider", exact: true }).click(); dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Configuration revision", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Assign provider", exact: true }).click(); await expect(dialog).toHaveCount(0);
  await expect(binding.getByText("Local SMTP demo · r1", { exact: true })).toHaveCount(2);
  await page.screenshot({ path: test.info().outputPath("provider-bindings.png"), fullPage: true, animations: "disabled" });
  await page.getByRole("tab", { name: "Configurations", exact: true }).click();
  await row.getByRole("button", { name: "Configure", exact: true }).click(); dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Save new revision", exact: true }).click(); await expect(dialog).toHaveCount(0);
  await expect(row.getByText("r2", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Channel bindings", exact: true }).click();
  await expect(binding.getByText("Local SMTP demo · r1", { exact: true })).toHaveCount(2);
  const concurrent = { scope: "environment", project_id: projectId, environment_id: env.id, channel: "email", expected_generation: 1, revision_id: item.latest.id };
  const outcomes = await Promise.all([1, 2].map(() => page.request.put("/api/v1/providers/bindings", { headers, data: concurrent })));
  expect(outcomes.map((value) => value.status()).sort()).toEqual([200, 409]);
  const secret = "fictional-browser-smtp-password";
  const secured = await (await page.request.post("/api/v1/providers", { headers, data: { name: "Credential rotation demo", provider_type: "smtp", project_id: projectId, config: { host: "mailpit", port: 587, tls: "starttls", sender: "sender@example.test", username: "synthetic", password: secret } } })).json();
  expect(JSON.stringify(secured)).not.toContain(secret);
  await page.getByRole("tab", { name: "Configurations", exact: true }).click();
  await page.getByRole("button", { name: "Refresh providers", exact: true }).click();
  const secureRow = page.getByRole("row").filter({ hasText: "Credential rotation demo" });
  await secureRow.getByRole("button", { name: "Configure", exact: true }).click(); dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Password", { exact: true })).toHaveValue("");
  await dialog.getByLabel("Password", { exact: true }).fill("replacement-browser-smtp-password");
  await dialog.getByRole("button", { name: "Save new revision", exact: true }).click(); await expect(dialog).toHaveCount(0);
  const revisions = await (await page.request.get(`/api/v1/providers/${secured.id}/revisions`)).json();
  expect(revisions).toHaveLength(2); expect(JSON.stringify(revisions)).not.toContain(secret); expect(JSON.stringify(revisions)).not.toContain("replacement-browser-smtp-password");
  expect(revisions[0].configured_secrets).toEqual(["password"]);
  await page.screenshot({ path: test.info().outputPath("providers.png"), fullPage: true, animations: "disabled" });
});

test("cloud provider contracts configure SES and Firebase and deliver through separate workers", async ({ page }) => {
  test.skip(process.env.COMPOSE_FILE?.includes("voxriva-cloud-compose") !== true, "Run scripts/test-cloud-compose.sh for deterministic cloud transports");
  await page.setViewportSize({ width: 1440, height: 1000 });
  const csrf = { "X-CSRF-Token": (await (await page.request.get("/api/v1/auth/session")).json()).csrf_token };
  async function post(path: string, data: object) { const result = await page.request.post(`/api/v1${path}`, { headers: csrf, data }); expect(result.ok(), await result.text()).toBeTruthy(); return result.json(); }
  const project = await post("/projects", { name: "Cloud contracts" });
  const env = await post(`/projects/${project.id}/environments`, { name: "dev" });
  await page.goto("/providers");
  async function choose(label: string, option: string) {
    await chooseOption(page, page.getByRole("dialog").getByLabel(label, { exact: true }), option);
  }
  async function addProvider(type: string, name: string) {
    await page.getByRole("button", { name: "Add provider", exact: true }).click();
    await choose("Provider type", type);
    await page.getByRole("dialog").getByLabel("Name", { exact: true }).fill(name);
    await choose("Owner", "Cloud contracts");
  }
  await addProvider("Amazon SES · email", "SES contract");
  await page.getByRole("dialog").getByLabel("Verified sender email", { exact: true }).fill("sender@example.test");
  await page.getByRole("dialog").getByRole("button", { name: "Create provider", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await addProvider("Firebase Cloud Messaging · push", "Firebase contract");
  await expect(page.getByRole("dialog").getByLabel("Service account JSON", { exact: true })).toBeVisible();
  await page.getByRole("dialog").getByLabel("Firebase project ID", { exact: true }).fill("firebase-demo");
  await choose("Authentication", "Workload credentials");
  await page.getByRole("dialog").getByRole("button", { name: "Create provider", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const firebaseRow = page.getByRole("row").filter({ hasText: "Firebase contract" });
  await firebaseRow.getByRole("button", { name: "Test push", exact: true }).click();
  const dialog = page.getByRole("dialog");
  const device = "synthetic-device-token-hidden-from-history";
  await dialog.getByLabel("Device registration token", { exact: true }).fill(device);
  await expect(dialog.getByLabel("Send to device (deliver a real push)")).not.toBeChecked();
  const validation = page.waitForRequest((request) => request.url().endsWith("/send-test-push"));
  await dialog.getByRole("button", { name: "Run push test", exact: true }).click();
  expect((await validation).postDataJSON().validate_only).toBe(true);
  await expect(page.getByText("Firebase contract: FCM validated the push without delivery.", { exact: true })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("cloud-providers.png"), fullPage: true, animations: "disabled" });
  const providers = await (await page.request.get("/api/v1/providers")).json();
  const email = providers.find((item: { name: string }) => item.name === "SES contract");
  const push = providers.find((item: { name: string }) => item.name === "Firebase contract");
  for (const [channel, provider] of [["email", email], ["push", push]] as const) {
    expect((await page.request.put("/api/v1/providers/bindings", { headers: csrf, data: { scope: "project", project_id: project.id, channel, expected_generation: 0, revision_id: provider.latest.id } })).status()).toBe(200);
  }
  const key = await post(`/projects/${project.id}/environments/${env.id}/keys`, { name: "Cloud contract key" });
  const notifications: { id: string; status_url: string; channel: string }[] = [];
  compose("stop", "email-worker", "push-worker");
  try {
    for (const channel of ["email", "push"]) {
      const draft = channel === "email" ? { subject: "SES {{ name }}", text: "Hello {{ name }}" } : { title: "FCM {{ name }}", body: "Hello {{ name }}", data: { screen: "home" } };
      const template = await post("/templates", { name: `Cloud ${channel}`, key: `cloud-${channel}`, channel, project_ids: [project.id], draft: { ...draft, variable_schema: { type: "object", properties: { name: { type: "string" } }, required: ["name"] }, preview_context: { name: "Preview" } } });
      const version = await post(`/templates/${template.id}/publish`, { branch_id: template.branch_id, expected_revision: 1 });
      await post(`/templates/${template.id}/deployments/deploy`, { scope: "environment", project_id: project.id, environment_id: env.id, locale: "en", expected_generation: 0, version_id: version.id });
      const request = { template_key: template.key, context: { name: "Runtime" }, ...(channel === "email" ? { recipient: "synthetic@example.test" } : { device_token: device }) };
      const accepted = await page.request.post("/api/v1/notifications", { headers: { Authorization: `Bearer ${key.key}`, "Idempotency-Key": `cloud-${channel}` }, data: request });
      expect(accepted.status(), await accepted.text()).toBe(202); notifications.push({ ...await accepted.json(), channel });
    }
    await expect.poll(() => Number(compose("exec", "-T", "redis", "redis-cli", "LLEN", "push").trim())).toBe(1);
    await expect.poll(() => Number(compose("exec", "-T", "redis", "redis-cli", "LLEN", "email").trim())).toBe(1);
    compose("start", "email-worker");
    await expect.poll(async () => (await (await page.request.get(notifications[0].status_url)).json()).status, { timeout: 30000 }).toBe("sent");
    expect((await (await page.request.get(notifications[1].status_url)).json()).status).toBe("queued");
    compose("start", "push-worker");
    await expect.poll(async () => (await (await page.request.get(notifications[1].status_url)).json()).status, { timeout: 30000 }).toBe("sent");
  } finally { compose("start", "email-worker", "push-worker"); }
  await page.goto(`/notifications/${notifications[1].id}`);
  await expect(page.getByText("Accepted by FCM. Device delivery is not confirmed.", { exact: true })).toBeVisible();
  await expect(page.getByText("Device token · hidden", { exact: true })).toBeVisible();
  expect(await page.locator("main, .content-frame").last().innerText()).not.toContain(device);
  await page.screenshot({ path: test.info().outputPath("cloud-push-delivery.png"), fullPage: true, animations: "disabled" });
  const detail = await (await page.request.get(notifications[1].status_url)).json();
  expect(detail.attempts).toHaveLength(1); expect(JSON.stringify(detail)).not.toContain(device);
  await nav(page, "Operations").click();
  await expect(page.getByRole("heading", { name: "Workers", exact: true })).toBeVisible();
  await expect(page.getByText(/^push@/).first()).toBeVisible({ timeout: 15000 });
  await expect(page.getByText(/^email@/).first()).toBeVisible();
});
