import { expect, test } from "@playwright/test";
import { chooseOption, compose, setup, signIn } from "./support/compose";

setup();

test("notification pagination and combined email filters restore URLs without crossing project access boundaries", async ({ page, browser }) => {
  await page.setViewportSize({ width: 1540, height: 1100 });
  const csrf = { "X-CSRF-Token": (await (await page.request.get("/api/v1/auth/session")).json()).csrf_token };
  async function post(path: string, data: object, expected = 201) {
    const response = await page.request.post(`/api/v1${path}`, { headers: csrf, data });
    expect(response.status(), await response.text()).toBe(expected);
    return response.json();
  }
  const project = await post("/projects", { name: "Notification filter workspace" });
  const privateProject = await post("/projects", { name: "Private notification workspace" });
  const dev = await post(`/projects/${project.id}/environments`, { name: "filter-dev" });
  const prod = await post(`/projects/${project.id}/environments`, { name: "filter-prod" });
  const privateEnvironment = await post(`/projects/${privateProject.id}/environments`, { name: "private-filter-env" });
  const template = await post("/templates", {
    name: "Notification filter fixture", key: "audit-notification-filters", channel: "email", project_ids: [project.id, privateProject.id],
    draft: { subject: "Synthetic pagination fixture", text: "Queued test data; no transport delivery is needed.", variable_schema: { type: "object", properties: {}, additionalProperties: false }, preview_context: {} },
  });
  const version = await post(`/templates/${template.id}/publish`, { branch_id: template.branch_id, expected_revision: 1 });
  const provider = await post("/providers", { name: "Filter-only local SMTP", provider_type: "smtp", config: { host: "mailpit", port: 1025, tls: "none", sender: "filter-fixture@example.test" } });
  async function prepareEnvironment(projectId: string, environmentId: string) {
    const target = { scope: "environment", project_id: projectId, environment_id: environmentId, locale: "en" };
    await post(`/templates/${template.id}/deployments/deploy`, { ...target, expected_generation: 0, version_id: version.id }, 200);
    const binding = await page.request.put("/api/v1/providers/bindings", { headers: csrf, data: { ...target, channel: "email", expected_generation: 0, revision_id: provider.latest.id } });
    expect(binding.status(), await binding.text()).toBe(200);
    return post(`/projects/${projectId}/environments/${environmentId}/keys`, { name: "Pagination synthetic fixture" });
  }
  const devKey = await prepareEnvironment(project.id, dev.id);
  const prodKey = await prepareEnvironment(project.id, prod.id);
  const privateKey = await prepareEnvironment(privateProject.id, privateEnvironment.id);
  const viewerEmail = "notification-filter-viewer@example.test";
  const viewerPassword = "Synthetic filter viewer password";
  await post(`/projects/${project.id}/members`, { email: viewerEmail, display_name: "Filter-only viewer", password: viewerPassword, role: "viewer" });

  const recipient = "audit.filters.needle@example.test";
  const privateRecipient = "private.filters.needle@example.test";
  const prodRecipient = "production.filters.needle@example.test";
  const identifiers: string[] = [];
  let privateIdentifier = "";
  const sql = (statement: string) => compose("exec", "-T", "postgres", "psql", "-U", "voxriva", "-d", "voxriva", "-Atc", statement).trim();
  const mailboxTotal = () => JSON.parse(compose("exec", "-T", "api", "python", "-c", "import json,urllib.request; print(urllib.request.urlopen('http://mailpit:8025/api/v1/messages').read().decode())")).total;
  const deliveries = page.getByRole("link", { name: "View delivery", exact: true });
  const search = page.getByRole("searchbox", { name: "Search recipient email", exact: true });
  const select = (label: string, value: string) => chooseOption(page, page.getByRole("combobox", { name: label, exact: true }), value);
  const params = () => new URL(page.url()).searchParams;
  const expectFirstPage = async () => { await expect.poll(() => params().get("page")).toBeNull(); };
  const before = mailboxTotal();
  compose("stop", "email-worker");
  try {
    async function accept(key: string, email: string, index: string) {
      const result = await page.request.post("/api/v1/notifications", { headers: { Authorization: `Bearer ${key}`, "Idempotency-Key": `audit-filter-${index}` }, data: { template_key: template.key, recipient: email, context: {} } });
      expect(result.status(), await result.text()).toBe(202);
      const item = await result.json();
      identifiers.push(item.id);
      return item.id as string;
    }
    // The oldest matching email lives beyond the first 25 rows. Every row uses
    // real acceptance/encryption; the stopped worker prevents bulk test sends.
    const needleIdentifier = await accept(devKey.key, recipient, "needle");
    for (let index = 1; index < 28; index++) {
      await accept(devKey.key, `audit.filters.${String(index).padStart(2, "0")}@example.test`, `dev-${index}`);
    }
    const expiredIdentifier = await accept(devKey.key, "expired.filters@example.test", "expired");
    sql(`UPDATE notifications SET expires_at=now()-interval '1 minute' WHERE id='${expiredIdentifier}'`);
    await expect.poll(async () => (await (await page.request.get(`/api/v1/notifications/${expiredIdentifier}`)).json()).status, { timeout: 15_000 }).toBe("failed");
    await accept(prodKey.key, prodRecipient, "production");
    privateIdentifier = await accept(privateKey.key, privateRecipient, "private");
    expect(identifiers).toHaveLength(31);

    const initial = new URLSearchParams({ project: project.id, environment: dev.id, status: "queued", channel: "email" });
    await page.goto(`/notifications?${initial}`);
    await expect(deliveries).toHaveCount(25);
    await expect(page.getByText(recipient, { exact: true })).toHaveCount(0);
    await page.getByTitle("Next Page", { exact: true }).click();
    await expect.poll(() => params().get("page")).toBe("2");
    await expect(deliveries).toHaveCount(3);
    await expect(page.getByText(recipient, { exact: true })).toBeVisible();
    const pageTwoUrl = page.url();
    await page.reload();
    await expect(page).toHaveURL(pageTwoUrl);
    await expect(deliveries).toHaveCount(3);
    await expect(page.getByText(recipient, { exact: true })).toBeVisible();

    // Changing an environment from page 2 must reset its offset rather than
    // incorrectly reporting an empty second page for a one-row environment.
    await select("Notification environment", "Notification filter workspace / filter-prod");
    await expectFirstPage();
    await expect(deliveries).toHaveCount(1);
    await expect(page.getByText(prodRecipient, { exact: true })).toBeVisible();
    await select("Notification environment", "Notification filter workspace / filter-dev");
    await expect(deliveries).toHaveCount(25);
    await page.getByTitle("Next Page", { exact: true }).click();
    await expect.poll(() => params().get("page")).toBe("2");

    const filteredRequest = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return response.request().method() === "GET" && url.pathname === "/api/v1/notifications" && url.searchParams.get("recipient_email") === "FILTERS.NEEDLE";
    });
    await search.fill("FILTERS.NEEDLE");
    await search.press("Enter");
    const filtered = await filteredRequest;
    expect(filtered.status()).toBe(200);
    const requestParams = new URL(filtered.url()).searchParams;
    expect(Object.fromEntries(requestParams)).toMatchObject({ project_id: project.id, environment_id: dev.id, status: "queued", channel: "email", recipient_email: "FILTERS.NEEDLE", offset: "0", limit: "25" });
    const result = await filtered.json();
    expect(result.total).toBe(1);
    expect(result.items.map((item: { id: string }) => item.id)).toEqual([needleIdentifier]);
    await expectFirstPage();
    await expect(deliveries).toHaveCount(1);
    await expect(page.getByText(recipient, { exact: true })).toBeVisible();
    expect(params().get("environment")).toBe(dev.id);
    expect(params().get("status")).toBe("queued");
    expect(params().get("channel")).toBe("email");

    await select("Notification status", "Failed");
    await expect(deliveries).toHaveCount(0);
    await expect(page.getByText("No notifications match these filters. Submit a notification using an environment API key to begin.", { exact: true })).toBeVisible();
    await select("Notification status", "Queued");
    await expect(deliveries).toHaveCount(1);
    await select("Notification channel", "Push");
    await expect(deliveries).toHaveCount(0);
    await select("Notification channel", "Email");
    await expect(deliveries).toHaveCount(1);

    await select("Notification project", "Private notification workspace");
    await expect.poll(() => params().get("environment")).toBeNull();
    await expectFirstPage();
    await expect(deliveries).toHaveCount(1);
    await expect(page.getByText(privateRecipient, { exact: true })).toBeVisible();
    await expect(page.getByText(recipient, { exact: true })).toHaveCount(0);
    await select("Notification project", "Notification filter workspace");
    await expect(deliveries).toHaveCount(2);
    await select("Notification environment", "Notification filter workspace / filter-dev");
    await expect(deliveries).toHaveCount(1);

    await search.fill("no-such-synthetic-filter-address");
    await search.press("Enter");
    await expect(deliveries).toHaveCount(0);
    const emptyUrl = page.url();
    await page.reload();
    await expect(page).toHaveURL(emptyUrl);
    await expect(search).toHaveValue("no-such-synthetic-filter-address");
    await expect(deliveries).toHaveCount(0);
    await search.fill("FILTERS.NEEDLE");
    await search.press("Enter");
    await expect(deliveries).toHaveCount(1);
    const restoredUrl = page.url();
    await page.reload();
    await expect(page).toHaveURL(restoredUrl);
    await expect(search).toHaveValue("FILTERS.NEEDLE");
    await expect(deliveries).toHaveCount(1);
    await expect(page.getByText(recipient, { exact: true })).toBeVisible();

    const viewerContext = await browser.newContext({ baseURL: process.env.VOXRIVA_TEST_URL });
    try {
      const viewer = await viewerContext.newPage();
      await viewer.goto("/");
      await signIn(viewer, viewerEmail, viewerPassword);
      await viewer.goto("/notifications?recipient_email=FILTERS.NEEDLE&status=queued&channel=email");
      await expect(viewer.getByRole("link", { name: "View delivery", exact: true })).toHaveCount(2);
      await expect(viewer.getByText(recipient, { exact: true })).toBeVisible();
      await expect(viewer.getByText(prodRecipient, { exact: true })).toBeVisible();
      await expect(viewer.getByText(privateRecipient, { exact: true })).toHaveCount(0);
      const own = await (await viewer.request.get(`/api/v1/notifications?recipient_email=FILTERS.NEEDLE&status=queued&channel=email`)).json();
      expect(own.total).toBe(2);
      expect(own.items.every((item: { project_id: string }) => item.project_id === project.id)).toBe(true);
      expect((await viewer.request.get(`/api/v1/notifications?project_id=${privateProject.id}&recipient_email=FILTERS.NEEDLE`)).status()).toBe(404);
      expect((await viewer.request.get(`/api/v1/notifications/${privateIdentifier}`)).status()).toBe(404);
      await viewer.goto(`/notifications?project=${privateProject.id}&recipient_email=FILTERS.NEEDLE`);
      await expect(viewer.getByRole("alert").filter({ hasText: "Project not found" })).toBeVisible();
      await expect(viewer.getByRole("link", { name: "View delivery", exact: true })).toHaveCount(0);
      await expect(viewer.getByText(privateRecipient, { exact: true })).toHaveCount(0);
    } finally { await viewerContext.close(); }
    expect(mailboxTotal()).toBe(before);
  } finally {
    // Drop only this spec's queued/expired fixture records before restarting the
    // worker. Any already-published IDs then safely resolve to missing rows.
    try {
      if (identifiers.length) {
        expect(identifiers.every((value) => /^[0-9a-f-]{36}$/.test(value))).toBe(true);
        sql(`DELETE FROM notification_outbox WHERE notification_id IN (${identifiers.map((value) => `'${value}'`).join(",")}); DELETE FROM notifications WHERE id IN (${identifiers.map((value) => `'${value}'`).join(",")});`);
        expect(sql(`SELECT count(*) FROM notifications WHERE project_id IN ('${project.id}','${privateProject.id}')`)).toBe("0");
      }
    } finally { compose("start", "email-worker"); }
  }
});
