import { expect, test } from "@playwright/test";
import { compose, setup } from "./support/compose";

setup();

test("replays an expired payload only after valid recipient and runtime context are supplied again", async ({ page }) => {
  const csrf = { "X-CSRF-Token": (await (await page.request.get("/api/v1/auth/session")).json()).csrf_token };
  async function post(path: string, data: object) {
    const response = await page.request.post(`/api/v1${path}`, { headers: csrf, data });
    expect(response.ok(), await response.text()).toBeTruthy();
    return response.json();
  }
  const project = await post("/projects", { name: "Expired payload replay" });
  const environment = await post(`/projects/${project.id}/environments`, { name: "expired-replay" });
  const template = await post("/templates", {
    name: "Expired replay welcome", key: "expired-replay-welcome", channel: "email", project_ids: [project.id],
    draft: {
      subject: "Expired replay {{ name }}", text: "Hello {{ name }}", html: "",
      variable_schema: { type: "object", properties: { name: { type: "string" } }, required: ["name"], additionalProperties: false },
      preview_context: { name: "PREVIEW_MUST_NEVER_DELIVER" },
    },
  });
  const version = await post(`/templates/${template.id}/publish`, { branch_id: template.branch_id, expected_revision: 1 });
  const target = { scope: "environment", project_id: project.id, environment_id: environment.id, locale: "en" };
  await post(`/templates/${template.id}/deployments/deploy`, { ...target, expected_generation: 0, version_id: version.id });
  const provider = await post("/providers", {
    name: "Expired replay SMTP", provider_type: "smtp", project_id: project.id,
    config: { host: "mailpit", port: 1025, tls: "none", sender: "expired-replay@example.test" },
  });
  expect((await page.request.put("/api/v1/providers/bindings", {
    headers: csrf, data: { ...target, channel: "email", expected_generation: 0, revision_id: provider.latest.id },
  })).status()).toBe(200);
  const key = await post(`/projects/${project.id}/environments/${environment.id}/keys`, { name: "Expired replay integration" });
  const database = ["exec", "-T", "postgres", "psql", "-U", "voxriva", "-d", "voxriva", "-Atc"];
  const mailbox = () => JSON.parse(compose("exec", "-T", "api", "python", "-c",
    "import urllib.request; print(urllib.request.urlopen('http://mailpit:8025/api/v1/messages').read().decode())"));
  const before = mailbox().total;
  const originalRecipient = "expired.original@example.test";
  const replacementRecipient = "expired.resupplied@example.test";

  compose("stop", "email-worker");
  try {
    const accepted = await page.request.post("/api/v1/notifications", {
      headers: { Authorization: `Bearer ${key.key}`, "Idempotency-Key": "expired-replay-original" },
      data: { template_key: template.key, recipient: originalRecipient, context: { name: "ORIGINAL_RUNTIME_NEVER_SENT" } },
    });
    expect(accepted.status()).toBe(202);
    const original = await accepted.json();
    expect(original.id).toMatch(/^[a-f0-9-]{36}$/i);
    const originalPath = `/api/v1/notifications/${original.id}`;
    const detail = async () => (await page.request.get(originalPath)).json();
    expect((await detail()).status).toBe("queued");

    // Move only this fixture's retention deadline. The real relay performs the
    // expiration transition and deletes runtime data while the worker is paused.
    expect(compose(...database, `UPDATE notifications SET expires_at=now()-INTERVAL '1 second' WHERE id='${original.id}' AND status='queued'`).trim()).toBe("UPDATE 1");
    await expect.poll(async () => (await detail()).status, { timeout: 15_000 }).toBe("failed");
    const expired = await detail();
    expect(expired.error_code).toBe("payload_expired");
    expect(expired.payload_available).toBe(false);
    expect(expired.replay_allowed).toBe(true);
    expect(expired.attempts).toHaveLength(0);
    expect(compose(...database, `SELECT status,(encrypted_payload IS NULL),(encrypted_recipient IS NOT NULL) FROM notifications WHERE id='${original.id}'`).trim()).toBe("failed|t|t");
    expect(mailbox().total).toBe(before);

    await page.goto(`/notifications/${original.id}`);
    await page.getByRole("button", { name: "Replay failed notification", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Replay failed notification", exact: true });
    await expect(dialog.getByText("Runtime input has expired. Supply it again to replay.", { exact: true })).toBeVisible();
    const recipient = dialog.getByLabel("Recipient", { exact: true });
    const context = dialog.getByLabel("Runtime context (JSON)", { exact: true });
    const confirm = dialog.getByRole("button", { name: "Confirm replay", exact: true });
    const replayRequests: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && new URL(request.url()).pathname === `${originalPath}/replay`) replayRequests.push(request.url());
    });

    await confirm.click();
    await expect(recipient).toHaveAttribute("aria-invalid", "true");
    await expect(context).toHaveAttribute("aria-invalid", "true");
    expect(replayRequests).toHaveLength(0);
    await recipient.fill("not-an-email");
    await context.fill("{}");
    await confirm.click();
    await expect(recipient).toHaveAttribute("aria-invalid", "true");
    expect(replayRequests).toHaveLength(0);

    await recipient.fill(replacementRecipient);
    await context.fill("{");
    await confirm.click();
    await expect(dialog.getByText("Enter valid JSON runtime context.", { exact: true })).toBeVisible();
    expect(replayRequests).toHaveLength(0);
    await context.fill("[]");
    await confirm.click();
    await expect(dialog.getByText("Runtime context must be a JSON object.", { exact: true })).toBeVisible();
    expect(replayRequests).toHaveLength(0);

    await context.fill("{}");
    const replayResponse = () => page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname === `${originalPath}/replay`);
    const [invalidContext] = await Promise.all([replayResponse(), confirm.click()]);
    expect(invalidContext.status()).toBe(422);
    await expect(dialog.getByText("Runtime context does not match the published template.", { exact: true })).toBeVisible();
    await expect(page).toHaveURL(new URL(`/notifications/${original.id}`, process.env.VOXRIVA_TEST_URL!).href);
    expect(compose(...database, `SELECT count(*) FROM notifications WHERE replay_of_id='${original.id}'`).trim()).toBe("0");
    expect(mailbox().total).toBe(before);

    await context.fill('{"name":"RESUPPLIED_RUNTIME_ONLY"}');
    const [validReplay] = await Promise.all([replayResponse(), confirm.click()]);
    expect(validReplay.status()).toBe(202);
    const replayed = await validReplay.json();
    expect(replayed.id).not.toBe(original.id);
    expect(replayed.template_version_id).toBe(version.id);
    expect(replayed.provider_revision_id).toBe(provider.latest.id);
    await expect(page).toHaveURL(new URL(`/notifications/${replayed.id}?returnTo=${encodeURIComponent("/notifications")}`, process.env.VOXRIVA_TEST_URL!).href);
    compose("start", "email-worker");
    await expect.poll(async () => (await (await page.request.get(`/api/v1/notifications/${replayed.id}`)).json()).status, { timeout: 30_000 }).toBe("sent");
    await expect(page.getByText("Sent", { exact: true }).first()).toBeVisible();
    await expect(page.getByText(replacementRecipient, { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "the original delivery", exact: true })).toHaveAttribute("href", `/notifications/${original.id}?returnTo=${encodeURIComponent("/notifications")}`);
    await expect.poll(() => mailbox().total).toBe(before + 1);
    const messages = mailbox().messages.filter((message: { Subject: string }) => message.Subject.startsWith("Expired replay "));
    expect(messages).toHaveLength(1);
    expect(messages[0].Subject).toBe("Expired replay RESUPPLIED_RUNTIME_ONLY");
    expect(messages[0].To).toEqual([expect.objectContaining({ Address: replacementRecipient })]);

    const unchanged = await detail();
    expect(unchanged.status).toBe("failed");
    expect(unchanged.error_code).toBe("payload_expired");
    expect(unchanged.updated_at).toBe(expired.updated_at);
    expect(unchanged.recipient_email).toBe(originalRecipient);
    expect(unchanged.payload_available).toBe(false);
    expect(unchanged.attempts).toEqual(expired.attempts);
    expect(compose(...database, `SELECT count(*) FROM notifications WHERE replay_of_id='${original.id}'`).trim()).toBe("1");
    expect(compose(...database, `SELECT status,(encrypted_payload IS NULL) FROM notifications WHERE id='${replayed.id}'`).trim()).toBe("sent|t");
  } finally {
    compose("start", "email-worker");
  }
});
