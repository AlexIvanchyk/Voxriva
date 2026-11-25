import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { compose, setup } from "./support/compose";

test.describe("worker crash at observable delivery boundaries", () => {
  test.skip(process.env.VOXRIVA_WORKER_CRASH_E2E !== "1", "Run scripts/test-worker-crash-compose.sh for controllable worker barriers");
  setup();

  const sql = (query: string) => compose("exec", "-T", "postgres", "psql", "-U", "voxriva", "-d", "voxriva", "-Atc", query).trim();
  const barrier = (phase: string) => {
    const value = compose("exec", "-T", "api", "python", "-c", `from pathlib import Path; p=Path('/crash-state/${phase}.entered.json'); print(p.read_text() if p.exists() else 'null')`);
    return JSON.parse(value) as { phase: string; pid: number; message_id?: string } | null;
  };
  const release = (phase: string) => compose("exec", "-T", "api", "python", "-c", `from pathlib import Path; Path('/crash-state/${phase}.release').touch()`);
  const inbox = () => JSON.parse(compose("exec", "-T", "api", "python", "-c", "import urllib.request; print(urllib.request.urlopen('http://mailpit:8025/api/v1/messages').read().decode())")) as { messages: { Subject: string; MessageID: string }[] };
  const messages = (marker: string) => inbox().messages.filter((message) => message.Subject === `Worker crash ${marker}`);

  async function prepare(page: Page, marker: string) {
    const headers = { "X-CSRF-Token": (await (await page.request.get("/api/v1/auth/session")).json()).csrf_token };
    async function post(path: string, data: object) {
      const response = await page.request.post(`/api/v1${path}`, { headers, data });
      expect(response.ok(), await response.text()).toBeTruthy();
      return response.json();
    }
    const project = await post("/projects", { name: `Worker crash ${marker}` });
    const environment = await post(`/projects/${project.id}/environments`, { name: "dev" });
    const template = await post("/templates", {
      name: `Worker crash ${marker}`, key: `worker-crash-${marker}`, channel: "email", project_ids: [project.id],
      draft: { subject: "Worker crash {{ marker }}", text: "Synthetic crash boundary {{ marker }}", variable_schema: { type: "object", properties: { marker: { type: "string" } }, required: ["marker"], additionalProperties: false }, preview_context: { marker: "preview-only" } },
    });
    const version = await post(`/templates/${template.id}/publish`, { branch_id: template.branch_id, expected_revision: 1 });
    const target = { scope: "environment", project_id: project.id, environment_id: environment.id, locale: "en" };
    await post(`/templates/${template.id}/deployments/deploy`, { ...target, expected_generation: 0, version_id: version.id });
    const provider = await post("/providers", { name: `Crash SMTP ${marker}`, provider_type: "smtp", project_id: project.id, config: { host: "mailpit", port: 1025, tls: "none", sender: "worker-crash@example.test" } });
    expect((await page.request.put("/api/v1/providers/bindings", { headers, data: { ...target, channel: "email", expected_generation: 0, revision_id: provider.latest.id } })).status()).toBe(200);
    const key = await post(`/projects/${project.id}/environments/${environment.id}/keys`, { name: "Crash-only synthetic delivery key" });
    const response = await page.request.post("/api/v1/notifications", {
      headers: { Authorization: `Bearer ${key.key}`, "Idempotency-Key": `worker-crash-${marker}` },
      data: { template_key: template.key, recipient: `worker-crash-${marker}@example.test`, context: { marker } },
    });
    expect(response.status()).toBe(202);
    const accepted = await response.json();
    expect(accepted.id).toMatch(/^[0-9a-f-]{36}$/);
    return accepted.id as string;
  }

  function killWorker() {
    compose("kill", "--signal", "SIGKILL", "email-worker");
    const raw = compose("ps", "--all", "--format", "json", "email-worker").trim();
    const row = raw.startsWith("[") ? JSON.parse(raw)[0] : JSON.parse(raw.split("\n")[0]);
    expect(row.State).toBe("exited");
    expect(row.ExitCode).toBe(137);
  }

  function expireLease(identifier: string, token: string) {
    expect(token).toMatch(/^[0-9a-f-]{36}$/);
    expect(sql(`UPDATE notifications SET lease_expires_at=now()-INTERVAL '1 second' WHERE id='${identifier}' AND lease_token='${token}' AND status='processing' RETURNING id`)).toContain(identifier);
  }

  function staleOwnerCannotWrite(identifier: string, oldToken: string) {
    const result = sql(`UPDATE notifications SET error_code='stale_owner_must_not_write' WHERE id='${identifier}' AND status='processing' AND lease_token='${oldToken}' RETURNING id`);
    expect(result).toBe("UPDATE 0");
    expect(sql(`SELECT count(*) FROM notifications WHERE id='${identifier}' AND error_code='stale_owner_must_not_write'`)).toBe("0");
  }

  async function proveDuplicateTaskDoesNotSend(identifier: string, marker: string) {
    const notification = () => sql(`SELECT row_to_json(item)::text FROM notifications AS item WHERE id='${identifier}'`);
    const attempts = () => sql(`SELECT COALESCE(json_agg(attempt ORDER BY attempt.number)::text, '[]') FROM notification_attempts AS attempt WHERE notification_id='${identifier}'`);
    const beforeNotification = notification();
    const beforeAttempts = attempts();
    const beforeMessages = messages(marker);
    expect(beforeMessages).toHaveLength(1);
    // Telemetry stores the Celery event's task UUID in notification_id. A unique
    // task ID proves this injected task completed, rather than a late event from
    // the original task. Its argument still targets the original notification.
    const duplicateTaskId = randomUUID();
    expect(duplicateTaskId).not.toBe(identifier);
    const completions = () => Number(sql(`SELECT count(*) FROM worker_events WHERE notification_id='${duplicateTaskId}' AND event='task-succeeded'`));
    expect(completions()).toBe(0);
    compose("exec", "-T", "api", "python", "-c", `from backend.app.features.notifications.worker import celery_app; celery_app.send_task('voxriva.send_email', args=['${identifier}'], task_id='${duplicateTaskId}', queue='email', retry=False)`);
    await expect.poll(completions, { timeout: 20000 }).toBeGreaterThan(0);
    expect(notification()).toBe(beforeNotification);
    expect(attempts()).toBe(beforeAttempts);
    expect(messages(marker)).toEqual(beforeMessages);
    expect(messages(marker)).toHaveLength(1);
  }

  test("worker crash before send recovers with a new fenced claim and one observed SMTP delivery", async ({ page }) => {
    const marker = "before-send";
    try {
      const identifier = await prepare(page, marker);
      await expect.poll(() => barrier(marker)?.phase, { timeout: 20000 }).toBe(marker);
      const oldToken = sql(`SELECT lease_token FROM notifications WHERE id='${identifier}'`);
      expect(sql(`SELECT status || '|' || (send_started_at IS NULL)::text || '|' || attempt_count FROM notifications WHERE id='${identifier}'`)).toBe("processing|true|1");
      expect(messages(marker)).toHaveLength(0);
      killWorker();
      expireLease(identifier, oldToken);
      compose("start", "email-worker");
      await expect.poll(() => barrier("reclaimed-send")?.phase, { timeout: 30000 }).toBe("reclaimed-send");
      const newToken = sql(`SELECT lease_token FROM notifications WHERE id='${identifier}'`);
      expect(newToken).toMatch(/^[0-9a-f-]{36}$/);
      expect(newToken).not.toBe(oldToken);
      expect(sql(`SELECT status || '|' || attempt_count FROM notifications WHERE id='${identifier}'`)).toBe("processing|2");
      staleOwnerCannotWrite(identifier, oldToken);
      expect(messages(marker)).toHaveLength(0);
      release("reclaimed-send");
      await expect.poll(async () => (await (await page.request.get(`/api/v1/notifications/${identifier}`)).json()).status, { timeout: 30000 }).toBe("sent");
      const detail = await (await page.request.get(`/api/v1/notifications/${identifier}`)).json();
      expect(detail.attempts).toHaveLength(2);
      expect(detail.attempts.map((attempt: { status: string }) => attempt.status)).toEqual(["interrupted", "sent"]);
      expect(detail.attempts[0].error_code).toBe("worker_interrupted");
      expect(detail.attempts[0].retryable).toBe(true);
      expect(detail.payload_available).toBe(false);
      expect(messages(marker)).toHaveLength(1);
      await proveDuplicateTaskDoesNotSend(identifier, marker);
      await page.goto(`/notifications/${identifier}`);
      await expect(page.getByText("Sent", { exact: true }).first()).toBeVisible();
      await expect(page.getByText("Provider accepted the message", { exact: true })).toBeVisible();
    } finally {
      for (const phase of [marker, "reclaimed-send"]) release(phase);
      compose("start", "email-worker");
    }
  });

  test("worker crash after SMTP acceptance records conservative unknown without automatic resend", async ({ page }) => {
    const marker = "accepted-send";
    try {
      const identifier = await prepare(page, marker);
      await expect.poll(() => barrier(marker)?.phase, { timeout: 20000 }).toBe(marker);
      const receipt = barrier(marker)!;
      expect(receipt.message_id).toBeTruthy();
      expect(messages(marker)).toHaveLength(1);
      expect(messages(marker)[0].MessageID.replace(/[<>]/g, "")).toBe(receipt.message_id!.replace(/[<>]/g, ""));
      const oldToken = sql(`SELECT lease_token FROM notifications WHERE id='${identifier}'`);
      expect(sql(`SELECT status || '|' || (send_started_at IS NOT NULL)::text || '|' || attempt_count FROM notifications WHERE id='${identifier}'`)).toBe("processing|true|1");
      killWorker();
      expireLease(identifier, oldToken);
      await expect.poll(async () => (await (await page.request.get(`/api/v1/notifications/${identifier}`)).json()).status, { timeout: 20000 }).toBe("unknown");
      staleOwnerCannotWrite(identifier, oldToken);
      compose("start", "email-worker");
      const detail = await (await page.request.get(`/api/v1/notifications/${identifier}`)).json();
      expect(detail.attempts).toHaveLength(1);
      expect(detail.attempts[0]).toMatchObject({ status: "interrupted", retryable: false, error_code: "send_outcome_unknown", provider_message_id: null });
      expect(detail.error_code).toBe("send_outcome_unknown");
      expect(detail.payload_available).toBe(false);
      expect(detail.replay_allowed).toBe(false);
      await proveDuplicateTaskDoesNotSend(identifier, marker);
      expect(sql(`SELECT status || '|' || attempt_count FROM notifications WHERE id='${identifier}'`)).toBe("unknown|1");
      await page.goto(`/notifications/${identifier}`);
      await expect(page.getByText("Unknown", { exact: true }).first()).toBeVisible();
      await expect(page.getByRole("alert").filter({ hasText: "Provider acceptance could not be confirmed" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Replay failed notification", exact: true })).toHaveCount(0);
    } finally {
      release(marker);
      compose("start", "email-worker");
    }
  });
});
