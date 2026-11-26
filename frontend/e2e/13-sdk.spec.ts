import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { compose, setup } from "./support/compose";

setup();

test("Python SDK integration validates without sending and delivers through sync and async clients", async ({ page }) => {
  test.skip(!process.env.VOXRIVA_SDK_PYTHON, "Run scripts/test-sdk-compose.sh for a clean SDK installation");
  await page.setViewportSize({ width: 1440, height: 1000 });
  const csrf = { "X-CSRF-Token": (await (await page.request.get("/api/v1/auth/session")).json()).csrf_token };
  async function post(path: string, data: object) { const response = await page.request.post(`/api/v1${path}`, { headers: csrf, data }); expect(response.ok(), await response.text()).toBeTruthy(); return response.json(); }
  const project = await post("/projects", { name: "SDK integration" });
  const env = await post(`/projects/${project.id}/environments`, { name: "dev" });
  const template = await post("/templates", { name: "SDK welcome", key: "sdk-welcome", channel: "email", project_ids: [project.id], draft: { subject: "Welcome {{ name }}", text: "Hello {{ name }}", variable_schema: { type: "object", properties: { name: { type: "string" } }, required: ["name"] }, preview_context: { name: "PreviewOnly" } } });
  const version = await post(`/templates/${template.id}/publish`, { branch_id: template.branch_id, expected_revision: 1 });
  const provider = await post("/providers", { name: "SDK local SMTP", provider_type: "smtp", project_id: project.id, config: { host: "mailpit", port: 1025, tls: "none", sender: "sdk@example.test" } });
  await post(`/templates/${template.id}/deployments/deploy`, { scope: "environment", project_id: project.id, environment_id: env.id, locale: "en", expected_generation: 0, version_id: version.id });
  expect((await page.request.put("/api/v1/providers/bindings", { headers: csrf, data: { scope: "project", project_id: project.id, channel: "email", expected_generation: 0, revision_id: provider.latest.id } })).status()).toBe(200);
  const key = await post(`/projects/${project.id}/environments/${env.id}/keys`, { name: "SDK integration key" });
  await page.goto(`/api-keys?project=${project.id}&environment=${env.id}`);
  await page.getByRole("row").filter({ hasText: "SDK integration key" }).getByRole("button", { name: "Examples", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("SDK integration / dev", { exact: true })).toBeVisible();
  await dialog.getByRole("combobox", { name: "Integration template", exact: true }).fill("SDK welcome");
  await page.locator(".ant-select-dropdown:visible").getByText("SDK welcome · sdk-welcome", { exact: true }).click();
  await dialog.getByRole("tab", { name: "Python", exact: true }).click();
  const snippet = await dialog.getByRole("tabpanel", { name: "Python", exact: true }).locator(".integration-code").innerText();
  expect(snippet).toContain('client.validate("sdk-welcome"'); expect(snippet).toContain('os.environ["VOXRIVA_API_KEY"]');
  expect(snippet).toContain("\nfrom voxriva_sdk import Client"); expect(snippet).not.toContain(key.key);
  const wheel = await page.request.get("/downloads/voxriva_sdk-0.1.1-py3-none-any.whl");
  expect(wheel.status()).toBe(200); expect((await wheel.body()).subarray(0, 2).toString()).toBe("PK");
  const contract = await page.request.get("/downloads/delivery-v1.openapi.json");
  expect(contract.status()).toBe(200); expect((await contract.json()).info.version).toBe("1.0.0");
  await page.screenshot({ path: test.info().outputPath("sdk-integration-examples.png"), fullPage: true, animations: "disabled" });
  const python = process.env.VOXRIVA_SDK_PYTHON!;
  const smoke = fileURLToPath(new URL("../../sdk/python/tests/compose_smoke.py", import.meta.url));
  const result = JSON.parse(execFileSync(python, ["-I", smoke], { input: JSON.stringify({ base_url: process.env.VOXRIVA_TEST_URL, key: key.key, template_key: template.key, environment_id: env.id, template_version_id: version.id }), encoding: "utf8", timeout: 60000 }));
  expect(result.status).toBe("sent"); expect(result.sync_id).not.toBe(result.async_id);
  const count = compose("exec", "-T", "postgres", "psql", "-U", "voxriva", "-d", "voxriva", "-Atc", "SELECT count(*),count(encrypted_payload) FROM notifications");
  expect(count.trim()).toBe("2|0");
  const mail = JSON.parse(compose("exec", "-T", "api", "python", "-c", "import urllib.request; print(urllib.request.urlopen('http://mailpit:8025/api/v1/messages').read().decode())"));
  expect(mail.total).toBe(2);
  await page.goto(result.dashboard_url);
  await expect(page.getByText("SDK local SMTP · r1", { exact: true })).toBeVisible();
  await expect(page.getByText("Sent", { exact: true }).first()).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("sdk-delivery.png"), fullPage: true, animations: "disabled" });
});
