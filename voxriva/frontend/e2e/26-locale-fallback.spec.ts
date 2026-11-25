import { expect, test } from "@playwright/test";
import { compose, setup } from "./support/compose";

setup();

interface MailSummary { ID: string; Subject: string; To: { Address: string }[] }
interface Inbox { messages: MailSummary[] }
interface DeliveryDetail {
  id: string;
  status: string;
  locale: string;
  template_version_id: string;
  resolution: { resolved_locale: string; fallback_used: boolean; branch_name: string; template_version: number };
  attempts: { status: string }[];
}

test("missing runtime translations deliver the explicitly configured fallback and keep accepted locale revisions pinned", async ({ page }) => {
  const csrf = { "X-CSRF-Token": (await (await page.request.get("/api/v1/auth/session")).json()).csrf_token };
  async function post(path: string, data: object) {
    const response = await page.request.post(`/api/v1${path}`, { headers: csrf, data });
    expect(response.ok(), await response.text()).toBeTruthy();
    return response.json();
  }
  const project = await post("/projects", { name: "Runtime locale fallback" });
  const environment = await post(`/projects/${project.id}/environments`, { name: "fallback-dev" });
  const contract = { type: "object", properties: { name: { type: "string" } }, required: ["name"], additionalProperties: false };
  const englishDraft = {
    subject: "Welcome {{ name }}", text: "EN actual delivery for {{ name }}", html: "<h1>Welcome {{ name }}</h1>",
    variable_schema: contract, preview_context: { name: "PREVIEW_FIXTURE_ONLY" },
  };
  const template = await post("/templates", {
    name: "Runtime fallback welcome", key: "runtime-fallback-welcome", channel: "email", locale: "en",
    project_ids: [project.id], draft: englishDraft,
  });
  const base = `/templates/${template.id}`;
  const english = await post(`${base}/publish`, { branch_id: template.branch_id, expected_revision: template.draft_revision });
  const frenchBranch = await post(`${base}/branches`, { name: "translation-fr", locale: "fr", source_version_id: english.id });
  const frenchDraft = { ...englishDraft, subject: "Bonjour {{ name }}", text: "FR livraison réelle pour {{ name }}", html: "<h1>Bonjour {{ name }}</h1>" };
  const translated = await page.request.put(`/api/v1${base}/draft`, {
    headers: csrf, data: { branch_id: frenchBranch.id, expected_revision: frenchBranch.draft_revision, draft: frenchDraft },
  });
  expect(translated.status(), await translated.text()).toBe(200);
  const savedFrench = await translated.json();
  const french = await post(`${base}/publish`, { branch_id: frenchBranch.id, expected_revision: savedFrench.draft_revision });
  expect(english.locale).toBe("en");
  expect(french.locale).toBe("fr");
  expect(french.id).not.toBe(english.id);

  const target = { scope: "environment", project_id: project.id, environment_id: environment.id };
  for (const version of [english, french]) {
    await post(`${base}/deployments/deploy`, { ...target, locale: version.locale, expected_generation: 0, version_id: version.id });
  }
  const provider = await post("/providers", {
    name: "Locale fallback local SMTP", provider_type: "smtp", project_id: project.id,
    config: { host: "mailpit", port: 1025, tls: "none", sender: "locale.fallback@example.test" },
  });
  const binding = await page.request.put("/api/v1/providers/bindings", {
    headers: csrf, data: { ...target, channel: "email", expected_generation: 0, revision_id: provider.latest.id },
  });
  expect(binding.status(), await binding.text()).toBe(200);
  const key = await post(`/projects/${project.id}/environments/${environment.id}/keys`, { name: "Locale fallback synthetic integration" });
  const requestedLocale = "uk-UA"; // Neither this requested translation nor a Ukrainian branch/deployment exists.
  const canonicalLocale = requestedLocale.toLowerCase();
  const detail = async (id: string): Promise<DeliveryDetail> => {
    const response = await page.request.get(`/api/v1/notifications/${id}`);
    expect(response.status(), await response.text()).toBe(200);
    return response.json();
  };
  const inbox = (): Inbox => JSON.parse(compose("exec", "-T", "api", "python", "-c", "import urllib.request; print(urllib.request.urlopen('http://mailpit:8025/api/v1/messages?limit=100').read().decode())"));
  const fullMessage = (id: string): { Subject: string; Text: string } => JSON.parse(compose("exec", "-T", "api", "python", "-c", "import sys, urllib.request; print(urllib.request.urlopen('http://mailpit:8025/api/v1/message/'+sys.argv[1]).read().decode())", id));
  const frenchRecipient = "fallback.french.synthetic@example.test";
  const englishRecipient = "fallback.english.synthetic@example.test";
  expect(inbox().messages.filter((message) => message.To.some((recipient) => [frenchRecipient, englishRecipient].includes(recipient.Address)))).toHaveLength(0);

  compose("stop", "email-worker");
  try {
    const unacknowledged = await page.request.put(`/api/v1${base}/fallback`, { headers: csrf, data: { locale: "fr", expected_locale: "en" } });
    expect(unacknowledged.status()).toBe(409);
    expect((await unacknowledged.json()).detail).toContain("Explicitly acknowledge");
    expect((await (await page.request.get(`/api/v1${base}`)).json()).fallback_locale).toBe("en");
    const configuredFrench = await page.request.put(`/api/v1${base}/fallback`, {
      headers: csrf, data: { locale: "fr", expected_locale: "en", acknowledge_active_change: true },
    });
    expect(configuredFrench.status(), await configuredFrench.text()).toBe(200);
    expect(await configuredFrench.json()).toEqual({ fallback_locale: "fr" });

    async function accept(recipient: string, name: string, idempotencyKey: string) {
      const response = await page.request.post("/api/v1/notifications", {
        headers: { Authorization: `Bearer ${key.key}`, "Idempotency-Key": idempotencyKey },
        data: { template_key: template.key, locale: requestedLocale, recipient, context: { name } },
      });
      expect(response.status(), await response.text()).toBe(202);
      return response.json();
    }
    const first = await accept(frenchRecipient, "French runtime", "fallback-fr-before-change");
    expect(first.template_version_id).toBe(french.id);
    expect(await detail(first.id)).toMatchObject({ status: "queued", locale: canonicalLocale, resolution: { resolved_locale: "fr", fallback_used: true } });

    // Change the explicit fallback while the first delivery is queued. A later
    // resolution uses English; it must not rewrite the accepted French input.
    const configuredEnglish = await page.request.put(`/api/v1${base}/fallback`, {
      headers: csrf, data: { locale: "en", expected_locale: "fr", acknowledge_active_change: true },
    });
    expect(configuredEnglish.status(), await configuredEnglish.text()).toBe(200);
    expect(await configuredEnglish.json()).toEqual({ fallback_locale: "en" });
    const second = await accept(englishRecipient, "English runtime", "fallback-en-after-change");
    expect(second.id).not.toBe(first.id);
    expect(second.template_version_id).toBe(english.id);
    expect(await detail(first.id)).toMatchObject({ status: "queued", template_version_id: french.id, resolution: { resolved_locale: "fr", fallback_used: true } });
    expect(await detail(second.id)).toMatchObject({ status: "queued", template_version_id: english.id, resolution: { resolved_locale: "en", fallback_used: true } });
    compose("start", "email-worker");

    const expected = [
      { accepted: first, recipient: frenchRecipient, version: french, subject: "Bonjour French runtime", text: "FR livraison réelle pour French runtime" },
      { accepted: second, recipient: englishRecipient, version: english, subject: "Welcome English runtime", text: "EN actual delivery for English runtime" },
    ];
    for (const row of expected) {
      await expect.poll(async () => (await detail(row.accepted.id)).status, { timeout: 30_000 }).toBe("sent");
      const sent = await detail(row.accepted.id);
      expect(sent.template_version_id).toBe(row.version.id);
      expect(sent.resolution).toMatchObject({ resolved_locale: row.version.locale, fallback_used: true });
      expect(sent.attempts).toHaveLength(1);
      expect(sent.attempts[0].status).toBe("sent");
      await expect.poll(() => inbox().messages.filter((message) => message.To.some((recipient) => recipient.Address === row.recipient)).length).toBe(1);
      const receipt = inbox().messages.find((message) => message.To.some((recipient) => recipient.Address === row.recipient))!;
      expect(receipt.Subject).toBe(row.subject);
      const delivered = fullMessage(receipt.ID);
      expect(delivered.Subject).toBe(row.subject);
      expect(delivered.Text.trim()).toBe(row.text);
      expect(delivered.Text).not.toContain("PREVIEW_FIXTURE_ONLY");

      await page.goto(`/notifications/${row.accepted.id}`);
      await expect(page.getByRole("heading", { name: "Delivery details", exact: true })).toBeVisible();
      await expect(page.getByText(`Fallback from ${canonicalLocale}`, { exact: true })).toBeVisible();
      await expect(page.getByText(`${row.version.branch_name} · v${row.version.number} · ${row.version.locale}`, { exact: true })).toBeVisible();
      await expect(page.getByText(row.recipient, { exact: true })).toBeVisible();
      await expect(page.getByText("Provider accepted the message", { exact: true })).toBeVisible();
    }
    // Re-read the older delivery after both workers completed: the configured
    // default changed, but its resolved language/version remained pinned.
    expect(await detail(first.id)).toMatchObject({ status: "sent", template_version_id: french.id, resolution: { resolved_locale: "fr", fallback_used: true } });
  } finally {
    compose("start", "email-worker");
  }
});
