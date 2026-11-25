import { expect, test } from "@playwright/test";
import { randomUUID, sign } from "node:crypto";
import { readFileSync } from "node:fs";
import { setup } from "./support/compose";

const topic = "arn:aws:sns:eu-west-1:123456789012:voxriva-e2e-events";
const certificateURL = "https://sns.eu-west-1.amazonaws.com/SimpleNotificationService-voxrivaE2E.pem";
// Public synthetic fixtures: the private key is test material, never an AWS key.
const signingKey = readFileSync(new URL("./fixtures/ses-events/signing-key.pem", import.meta.url));

type EventKind = "Delivery" | "Bounce";
interface Accepted { id: string; status_url: string }
interface Detail {
  status: string;
  attempts: { provider_message_id: string | null }[];
  provider_events: { id: string; event: string; occurred_at: string }[];
}

function signedEvent(messageId: string, kind: EventKind, occurredAt: string) {
  const envelope: Record<string, string> = {
    Type: "Notification",
    MessageId: randomUUID(),
    TopicArn: topic,
    Timestamp: new Date().toISOString(),
    Subject: "Synthetic SES delivery event",
    SignatureVersion: "2",
    SigningCertURL: certificateURL,
    Message: JSON.stringify({
      eventType: kind,
      mail: { messageId, destination: ["synthetic.ses@example.test"], private_test_marker: "private-sns-fixture-body" },
      [kind.toLowerCase()]: { timestamp: occurredAt },
    }),
  };
  const fields = ["Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"];
  const canonical = fields.map((field) => `${field}\n${envelope[field]}\n`).join("");
  envelope.Signature = sign("RSA-SHA256", Buffer.from(canonical), signingKey).toString("base64");
  return envelope;
}

setup();

test("verified SES events confirm delivery and bounce with signed duplicate and out-of-order handling", async ({ page }) => {
  test.skip(process.env.COMPOSE_FILE?.includes("voxriva-cloud-compose") !== true, "Run scripts/test-cloud-compose.sh for local SES transport/certificate retrieval doubles");
  const csrf = { "X-CSRF-Token": (await (await page.request.get("/api/v1/auth/session")).json()).csrf_token };
  async function post(path: string, data: object) {
    const response = await page.request.post(`/api/v1${path}`, { headers: csrf, data });
    expect(response.status(), await response.text()).toBe(201);
    return response.json();
  }
  const project = await post("/projects", { name: "Verified SES events" });
  const environment = await post(`/projects/${project.id}/environments`, { name: "events" });
  const provider = await post("/providers", {
    name: "Verified SES", provider_type: "aws_ses", project_id: project.id,
    config: { sender: "synthetic.ses@example.test", region: "eu-west-1", configuration_set: "e2e_verified_events", sns_topic_arn: topic },
  });
  expect((await page.request.put("/api/v1/providers/bindings", { headers: csrf, data: {
    scope: "project", project_id: project.id, channel: "email", expected_generation: 0, revision_id: provider.latest.id,
  } })).status()).toBe(200);
  const template = await post("/templates", {
    name: "Verified SES template", key: "verified-ses-events", channel: "email", project_ids: [project.id],
    draft: { subject: "Verified {{ name }}", text: "Hello {{ name }}", variable_schema: { type: "object", properties: { name: { type: "string" } }, required: ["name"] }, preview_context: { name: "Preview only" } },
  });
  const version = await post(`/templates/${template.id}/publish`, { branch_id: template.branch_id, expected_revision: 1 });
  const deployed = await page.request.post(`/api/v1/templates/${template.id}/deployments/deploy`, { headers: csrf, data: {
    scope: "environment", project_id: project.id, environment_id: environment.id, locale: "en", expected_generation: 0, version_id: version.id,
  } });
  expect(deployed.status(), await deployed.text()).toBe(200);
  const key = await post(`/projects/${project.id}/environments/${environment.id}/keys`, { name: "SES events key" });
  async function detail(notification: Accepted): Promise<Detail> {
    const response = await page.request.get(notification.status_url);
    expect(response.ok(), await response.text()).toBeTruthy();
    return response.json();
  }
  async function send(name: string): Promise<Accepted> {
    const response = await page.request.post("/api/v1/notifications", { headers: { Authorization: `Bearer ${key.key}`, "Idempotency-Key": `verified-ses-${name}` }, data: {
      template_key: template.key, recipient: `synthetic.${name}@example.test`, context: { name },
    } });
    expect(response.status(), await response.text()).toBe(202);
    const accepted: Accepted = await response.json();
    await expect.poll(async () => (await detail(accepted)).status, { timeout: 30000 }).toBe("sent");
    const sent = await detail(accepted);
    expect(sent.attempts).toHaveLength(1);
    expect(sent.attempts[0].provider_message_id).toMatch(/^local-ses-/);
    expect(sent.provider_events).toHaveLength(0);
    await page.goto(`/notifications/${accepted.id}`);
    await expect(page.getByText("Accepted by the provider. Inbox delivery is not yet confirmed.", { exact: true })).toBeVisible();
    return accepted;
  }
  const delivered = await send("delivered");
  const bounced = await send("bounced");
  const deliveredMessage = (await detail(delivered)).attempts[0].provider_message_id!;
  const bouncedMessage = (await detail(bounced)).attempts[0].provider_message_id!;
  expect(deliveredMessage).not.toBe(bouncedMessage);
  const eventURL = `/api/v1/providers/${provider.id}/events/ses`;
  async function submit(envelope: Record<string, string>, expected: "recorded" | "duplicate" = "recorded") {
    // Public SNS ingress, not an authenticated dashboard mutation: only its signature authorizes the event.
    const response = await page.request.post(eventURL, { data: envelope });
    expect(response.status(), await response.text()).toBe(202);
    expect(await response.json()).toEqual({ status: expected });
  }
  const now = Date.now();
  const recent = new Date(now - 10000).toISOString();
  const older = new Date(now - 20000).toISOString();
  const delivery = signedEvent(deliveredMessage, "Delivery", recent);
  // The certificate bytes are doubled, but production signature verification must reject a modified message.
  const tampered = await page.request.post(eventURL, { data: { ...delivery, Message: `${delivery.Message} ` } });
  expect(tampered.status()).toBe(403);
  expect((await detail(delivered)).provider_events).toHaveLength(0);
  expect((await detail(delivered)).status).toBe("sent");
  await submit(delivery);
  await expect.poll(async () => (await detail(delivered)).status).toBe("delivered");
  const firstEventId = (await detail(delivered)).provider_events[0].id;
  await submit(delivery, "duplicate");
  expect((await detail(delivered)).provider_events.map((event) => event.id)).toEqual([firstEventId]);
  // A late-arriving older bounce is kept as verified history and cannot undo a newer delivery.
  await submit(signedEvent(deliveredMessage, "Bounce", older));
  const deliveredHistory = await detail(delivered);
  expect(deliveredHistory.status).toBe("delivered");
  expect(deliveredHistory.provider_events.map((event) => event.event).sort()).toEqual(["bounced", "delivered"]);

  const bounce = signedEvent(bouncedMessage, "Bounce", recent);
  await submit(bounce);
  await expect.poll(async () => (await detail(bounced)).status).toBe("bounced");
  await submit(bounce, "duplicate");
  expect((await detail(bounced)).provider_events).toHaveLength(1);
  // Both an older delivery and a same-time delivery lose to the established bounce.
  await submit(signedEvent(bouncedMessage, "Delivery", older));
  await submit(signedEvent(bouncedMessage, "Delivery", recent));
  const bouncedHistory = await detail(bounced);
  expect(bouncedHistory.status).toBe("bounced");
  expect(bouncedHistory.provider_events).toHaveLength(3);
  expect(bouncedHistory.provider_events.map((event) => event.event).sort()).toEqual(["bounced", "delivered", "delivered"]);

  for (const [notification, confirmation, count, status] of [
    [delivered, "Delivery confirmed by a verified SES event.", 2, "Delivered"],
    [bounced, "A verified SES event reported a bounce. The message was not delivered.", 3, "Bounced"],
  ] as const) {
    await page.goto(`/notifications/${notification.id}`);
    await expect(page.getByText(confirmation, { exact: true })).toBeVisible();
    await expect(page.locator(".notification-summary").getByText(status, { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Verified provider events", exact: true })).toBeVisible();
    const history = page.getByRole("table").filter({ has: page.getByRole("columnheader", { name: "Event", exact: true }) });
    await expect(history.getByRole("row")).toHaveCount(count + 1);
    await expect(history.getByText("Bounced", { exact: true })).toHaveCount(1);
    await expect(history.getByText("Delivered", { exact: true })).toHaveCount(count - 1);
    const snapshot = await detail(notification);
    expect(snapshot.attempts).toHaveLength(1);
    expect(JSON.stringify(snapshot)).not.toContain("private-sns-fixture-body");
    expect(JSON.stringify(snapshot)).not.toContain("synthetic.ses@example.test");
  }
});
