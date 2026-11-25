import { expect, test } from "@playwright/test";
import { compose, createProject, createTemplate, editCode, setup } from "./support/compose";

setup();

test("format authoring roundtrips and delivers exact E.164 values with preview/runtime parity", async ({ page }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1560, height: 1100 });
  const projectId = await createProject(page, "Variable format integration");
  const id = await createTemplate(page, "Validated phone delivery");
  const base = `/api/v1/templates/${id}`;
  const csrf = { "X-CSRF-Token": (await (await page.request.get("/api/v1/auth/session")).json()).csrf_token };
  async function post(path: string, data: object) {
    const response = await page.request.post(path, { headers: csrf, data });
    expect(response.ok(), await response.text()).toBeTruthy();
    return response.json();
  }
  await editCode(page, "Email subject", "Phone {{ phone }}");
  await page.getByRole("tab", { name: "Plain text", exact: true }).click();
  await editCode(page, "Plain text", "Exact phone={{ phone }}; host={{ host }}");
  await page.getByRole("tab", { name: "Variables", exact: true }).click();
  const formats = [
    ["phone", "Phone number (E.164)", "phone"], ["host", "Hostname", "hostname"],
    ["ipv4", "IPv4 address", "ipv4"], ["ipv6", "IPv6 address", "ipv6"],
    ["duration", "Duration", "duration"], ["email", "Email address", "email"],
  ];
  for (const [name, label] of formats) {
    await page.getByLabel("New variable", { exact: true }).fill(name);
    await page.getByRole("button", { name: "Add variable", exact: true }).click();
    const control = page.getByRole("combobox", { name: `Format ${name}`, exact: true });
    await control.scrollIntoViewIfNeeded();
    await control.press("ArrowDown");
    const option = page.locator(".ant-select-dropdown:visible").getByText(label, { exact: true }).last();
    await option.scrollIntoViewIfNeeded();
    await option.click();
    await expect(page.locator(".ant-select-dropdown:visible")).toHaveCount(0);
    await page.getByRole("switch", { name: `Required ${name}`, exact: true }).click();
  }
  await expect(page.getByText(/Region is never inferred/).first()).toBeVisible();
  const phoneCard = page.locator(".variable-card").filter({ has: page.locator("code").getByText("phone", { exact: true }) });
  await phoneCard.getByText("Validation rules", { exact: true }).click();
  await page.getByLabel("Minimum length phone", { exact: true }).fill("8");
  await page.getByLabel("Maximum length phone", { exact: true }).fill("16");
  await page.getByLabel("Pattern phone", { exact: true }).fill("^\\+");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByText("Draft saved.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save draft", exact: true })).toHaveAttribute("aria-busy", "false");
  let saved = await (await page.request.get(base)).json();
  for (const [name, , format] of formats) expect(saved.draft.variable_schema.properties[name].format).toBe(format);
  expect(saved.draft.variable_schema.properties.phone).toMatchObject({ "x-voxriva-phone-version": 1, minLength: 8, maxLength: 16, pattern: "^\\+" });
  await page.reload();
  await page.getByRole("tab", { name: "Variables", exact: true }).click();
  await expect(page.getByText("Phone number (E.164)", { exact: true }).first()).toBeVisible();

  // Advanced schema and visual fields preserve each other, including nested formats.
  const schema = saved.draft.variable_schema;
  schema.properties.contacts = { type: "array", minItems: 1, items: { type: "object", properties: { phone: { type: "string", format: "phone", "x-voxriva-phone-version": 1 } }, required: ["phone"] } };
  schema.required.push("contacts");
  await editCode(page, "Schema JSON", JSON.stringify(schema));
  await page.getByRole("tab", { name: "Test data", exact: true }).click();
  await page.getByRole("button", { name: "Generate example", exact: true }).click();
  await expect(page.getByText("Example generated and validated against the variable contract.", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Test data phone", { exact: true })).toHaveValue("+12025550123");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByText("Draft saved.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save draft", exact: true })).toHaveAttribute("aria-busy", "false");
  saved = await (await page.request.get(base)).json();
  expect(saved.draft.variable_schema).toEqual(schema);
  const valid = saved.draft.preview_context;
  const preview = page.getByRole("region", { name: "Live preview" });
  await page.getByLabel("Test data phone", { exact: true }).fill("02083661177");
  await expect(preview.getByRole("alert").filter({ hasText: "context.phone:" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByText("Draft saved.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save draft", exact: true })).toHaveAttribute("aria-busy", "false");
  saved = await (await page.request.get(base)).json();
  const rejectedPublication = await page.request.post(`${base}/publish`, { headers: csrf, data: { branch_id: saved.branch_id, expected_revision: saved.draft_revision } });
  expect(rejectedPublication.status()).toBe(422);
  expect(await (await page.request.get(`${base}/versions`)).json()).toEqual([]);
  await page.getByLabel("Test data phone", { exact: true }).fill(valid.phone);
  await expect(preview.getByRole("alert").filter({ hasText: "context.phone:" })).toHaveCount(0);
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByText("Draft saved.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save draft", exact: true })).toHaveAttribute("aria-busy", "false");
  await page.reload();
  saved = await (await page.request.get(base)).json();
  expect(saved.draft.preview_context).toEqual(valid);
  expect(saved.draft.variable_schema).toEqual(schema);

  // All selected formats and nested paths use the same preview/runtime rules.
  const cases = [
    { ...valid, phone: "02083661177" }, { ...valid, phone: "+1 202 555 0123" },
    { ...valid, ipv4: "256.1.2.3" }, { ...valid, ipv6: "2001:::1" },
    { ...valid, host: "https://example.test/path" }, { ...valid, duration: "30 minutes" },
    { ...valid, email: "invalid" }, { ...valid, contacts: [{ phone: "02083661177" }] },
  ];
  const paths = ["phone", "phone", "ipv4", "ipv6", "host", "duration", "email", "contacts.0.phone"];
  const version = await post(`${base}/publish`, { branch_id: saved.branch_id, expected_revision: saved.draft_revision });
  const env = await post(`/api/v1/projects/${projectId}/environments`, { name: "format-dev" });
  const target = { scope: "environment", project_id: projectId, environment_id: env.id, locale: "en" };
  await post(`${base}/deployments/deploy`, { ...target, version_id: version.id, expected_generation: 0 });
  const provider = await post("/api/v1/providers", { name: "Format local SMTP", provider_type: "smtp", project_id: projectId, config: { host: "mailpit", port: 1025, tls: "none", sender: "formats@example.test" } });
  expect((await page.request.put("/api/v1/providers/bindings", { headers: csrf, data: { ...target, channel: "email", revision_id: provider.latest.id, expected_generation: 0 } })).status()).toBe(200);
  const key = await post(`/api/v1/projects/${projectId}/environments/${env.id}/keys`, { name: "Format delivery" });
  const auth = { Authorization: `Bearer ${key.key}` };
  const payload = (context: object) => ({ template_key: saved.key, recipient: "formats.synthetic@example.test", context });
  const counts = () => compose("exec", "-T", "postgres", "psql", "-U", "voxriva", "-d", "voxriva", "-Atc", "SELECT (SELECT count(*) FROM notifications),(SELECT count(*) FROM notification_outbox),(SELECT count(*) FROM notification_attempts)").trim();
  const mail = () => JSON.parse(compose("exec", "-T", "api", "python", "-c", "import urllib.request; print(urllib.request.urlopen('http://mailpit:8025/api/v1/messages').read().decode())"));
  const before = counts(); const mailboxBefore = mail().total;
  for (const [index, context] of cases.entries()) {
    const checked = await (await page.request.post(`${base}/preview`, { headers: csrf, data: { context } })).json();
    expect(checked.errors[0].path.join(".")).toBe(`context.${paths[index]}`);
    for (const endpoint of ["validate", "accept"]) {
      const response = await page.request.post(`/api/v1/notifications${endpoint === "validate" ? "/validate" : ""}`, { headers: { ...auth, "Idempotency-Key": `format-invalid-${index}` }, data: payload(context) });
      expect(response.status(), await response.text()).toBe(422);
      const issue = (await response.json()).detail.issues[0];
      expect(issue.path).toEqual(checked.errors[0].path); expect(issue.code).toBe(checked.errors[0].code);
    }
  }
  expect(counts()).toBe(before); expect(mail().total).toBe(mailboxBefore);
  for (const phone of ["+12025550123", "+442083661177", "+380501234567", "+359888123456"]) {
    expect((await page.request.post("/api/v1/notifications/validate", { headers: auth, data: payload({ ...valid, phone }) })).status()).toBe(200);
  }
  const phone = "+442083661177";
  const acceptedResponse = await page.request.post("/api/v1/notifications", { headers: { ...auth, "Idempotency-Key": "format-valid-exact" }, data: payload({ ...valid, phone }) });
  expect(acceptedResponse.status(), await acceptedResponse.text()).toBe(202);
  const accepted = await acceptedResponse.json();
  await expect.poll(async () => (await (await page.request.get(accepted.status_url, { headers: auth })).json()).status, { timeout: 30_000 }).toBe("sent");
  await expect.poll(() => mail().total).toBe(mailboxBefore + 1);
  const receipt = mail().messages.find((item: { Subject: string }) => item.Subject === `Phone ${phone}`);
  expect(receipt).toBeTruthy();
  const delivered = JSON.parse(compose("exec", "-T", "api", "python", "-c", "import sys,urllib.request; print(urllib.request.urlopen('http://mailpit:8025/api/v1/message/'+sys.argv[1]).read().decode())", receipt.ID));
  expect(delivered.Text.trim()).toBe(`Exact phone=${phone}; host=${valid.host}`);
  expect(delivered.Text).not.toContain(valid.phone);
  await page.screenshot({ path: test.info().outputPath("variable-formats-delivered.png"), fullPage: true, animations: "disabled" });
});
