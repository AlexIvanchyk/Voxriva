import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { compose, createProject, createTemplate, editCode, setup } from "./support/compose";
setup();
const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64");
test("uploads inserts reuses and persists static images with isolated preview and Image variables", async ({ page }) => {
  const projectId = await createProject(page, "Fictional images");
  const templateId = await createTemplate(page, "Fictional image email");
  await editCode(page, "Email subject", "Fictional logo");
  await editCode(page, "Email HTML", "<p>Logo</p>");
  await page.getByRole("button", { name: "Insert image", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Insert image" });
  await dialog.getByLabel("Upload image", { exact: true }).setInputFiles({ name: "logo.png", mimeType: "image/png", buffer: png });
  await dialog.getByLabel("Image alternative text").fill("Fictional brand");
  await dialog.getByLabel("Image width").fill("120");
  await dialog.getByRole("button", { name: "Insert image", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  const image = page.frameLocator('iframe[title="Email HTML preview"]').getByAltText("Fictional brand");
  await expect(image).toBeVisible();
  expect(await image.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth === 1)).toBeTruthy();
  expect(await page.locator('iframe[title="Email HTML preview"]').getAttribute("sandbox")).toBe("");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByText("Draft saved.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save draft", exact: true })).toHaveAttribute("aria-busy", "false");
  await page.reload(); await expect(image).toBeVisible();
  await page.getByRole("tab", { name: "Variables", exact: true }).click();
  await page.getByLabel("New variable", { exact: true }).fill("banner");
  await page.getByRole("button", { name: "Add variable", exact: true }).click();
  await page.getByRole("combobox", { name: "Type banner", exact: true }).press("ArrowDown");
  await page.locator('.ant-select-dropdown:visible').getByText("Image", { exact: true }).click();
  await page.getByRole("tab", { name: "Runtime defaults", exact: true }).click();
  await page.getByLabel("Upload Runtime default banner", { exact: true }).setInputFiles({ name: "banner.png", mimeType: "image/png", buffer: png });
  await page.getByRole("tab", { name: "Content", exact: true }).click();
  await page.getByRole("button", { name: "Insert image", exact: true }).click();
  await dialog.getByRole("combobox", { name: "Existing image" }).press("ArrowDown");
  await page.locator('.ant-select-dropdown:visible').getByText("banner · runtime default", { exact: true }).click();
  await dialog.getByLabel("Image alternative text").fill("Dynamic banner");
  await dialog.getByRole("button", { name: "Insert image", exact: true }).click();
  await expect(page.frameLocator('iframe[title="Email HTML preview"]').getByAltText("Dynamic banner")).toBeVisible();
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByText("Draft saved.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save draft", exact: true })).toHaveAttribute("aria-busy", "false");
  const csrf = { "X-CSRF-Token": (await (await page.request.get("/api/v1/auth/session")).json()).csrf_token };
  async function post(path: string, data: object) { const response = await page.request.post(`/api/v1${path}`, { headers: csrf, data }); expect(response.ok(), await response.text()).toBeTruthy(); return response.json(); }
  const base = `/templates/${templateId}`;
  const saved = await (await page.request.get(`/api/v1${base}`)).json();
  const version = await post(`${base}/publish`, { branch_id: saved.branch_id, expected_revision: saved.draft_revision });
  const environment = await post(`/projects/${projectId}/environments`, { name: "image-dev" });
  const target = { scope: "environment", project_id: projectId, environment_id: environment.id, locale: "en" };
  await post(`${base}/deployments/deploy`, { ...target, expected_generation: 0, version_id: version.id });
  const provider = await post("/providers", { name: "Fictional image SMTP", provider_type: "smtp", project_id: projectId, config: { host: "mailpit", port: 1025, tls: "none", sender: "images@example.test" } });
  expect((await page.request.put("/api/v1/providers/bindings", { headers: csrf, data: { ...target, channel: "email", expected_generation: 0, revision_id: provider.latest.id } })).status()).toBe(200);
  const key = await post(`/projects/${projectId}/environments/${environment.id}/keys`, { name: "Image SDK test" });
  const input = { template_key: saved.key, recipient: "invalid.image@example.test", context: { banner: { media_type: "image/png", content_base64: "PHN2Zy8+" } } };
  const before = compose("exec", "-T", "postgres", "psql", "-U", "voxriva", "-d", "voxriva", "-Atc", "SELECT (SELECT count(*) FROM notifications),(SELECT count(*) FROM notification_outbox)").trim();
  const invalid = await page.request.post("/api/v1/notifications", { headers: { Authorization: `Bearer ${key.key}`, "Idempotency-Key": "invalid-image" }, data: input });
  expect(invalid.status()).toBe(422);
  expect(compose("exec", "-T", "postgres", "psql", "-U", "voxriva", "-d", "voxriva", "-Atc", "SELECT (SELECT count(*) FROM notifications),(SELECT count(*) FROM notification_outbox)").trim()).toBe(before);
  const overrideBytes = "iVBORw0KGgoAAAANSUhEUgAAAAMAAAACCAIAAAASFvFNAAAAEElEQVR4nGP8zwAFTDAGAwATKQED8NgHhAAAAABJRU5ErkJggg==";
  const smoke = fileURLToPath(new URL("../../sdk/python/tests/image_smoke.py", import.meta.url));
  compose("stop", "email-worker");
  let ids: { default: string; override: string };
  try {
    ids = JSON.parse(execFileSync(process.env.VOXRIVA_SDK_PYTHON ?? fileURLToPath(new URL("../../.venv/bin/python", import.meta.url)), [smoke], { input: JSON.stringify({ base_url: process.env.VOXRIVA_TEST_URL, key: key.key, template_key: saved.key, override: overrideBytes }), encoding: "utf8", timeout: 30000 }));
    const changed = structuredClone(saved.draft); changed.images = {}; changed.html = "<p>Changed draft without images</p>"; changed.runtime_defaults = {};
    expect((await page.request.put(`/api/v1${base}/draft`, { headers: csrf, data: { expected_revision: saved.draft_revision, draft: changed } })).status()).toBe(200);
    // Even moving the deployment cannot change already accepted notifications.
    const next = await post(`${base}/publish`, { branch_id: saved.branch_id, expected_revision: saved.draft_revision + 1 });
    await post(`${base}/deployments/deploy`, { ...target, expected_generation: 1, version_id: next.id, allow_breaking: true });
    const frozen = await (await page.request.get(`/api/v1${base}/versions/${version.id}`)).json();
    expect(frozen.content.images).toEqual(saved.draft.images);
    expect(frozen.content.runtime_defaults).toEqual(saved.draft.runtime_defaults);
  } finally { compose("start", "email-worker"); }
  for (const id of Object.values(ids!)) {
    await expect.poll(async () => (await (await page.request.get(`/api/v1/notifications/${id}`)).json()).status, { timeout: 40000 }).toBe("sent");
    const status = await (await page.request.get(`/api/v1/notifications/${id}`)).json();
    expect(status.template_version_id).toBe(version.id);
    expect(compose("exec", "-T", "postgres", "psql", "-U", "voxriva", "-d", "voxriva", "-Atc", `SELECT count(encrypted_payload) FROM notifications WHERE id='${id}'`).trim()).toBe("0");
  }
  const mimeCheck = `import urllib.request,json,base64,hashlib
from email import policy
from email.parser import BytesParser
inbox=json.load(urllib.request.urlopen('http://mailpit:8025/api/v1/messages'))
result={}
for item in inbox['messages']:
 if item['Subject']!='Fictional logo': continue
 raw=urllib.request.urlopen('http://mailpit:8025/api/v1/message/'+item['ID']+'/raw').read()
 message=BytesParser(policy=policy.default).parsebytes(raw)
 html=message.get_body(preferencelist=('html',)).get_content()
 images=[]
 for part in message.walk():
  if part.get_content_maintype()!='image': continue
  data=part.get_payload(decode=True)
  cid=part['Content-ID'].strip('<>')
  assert cid==hashlib.sha256(data).hexdigest()+'@images.voxriva' and 'cid:'+cid in html
  assert part.get_content_disposition()=='inline'
  images.append(base64.b64encode(data).decode())
 result[str(message['To'])]=images
print(json.dumps(result))`;
  const delivered = JSON.parse(compose("exec", "-T", "api", "python", "-c", mimeCheck));
  expect(delivered["image.default@example.test"]).toEqual([png.toString("base64")]);
  expect(delivered["image.override@example.test"].sort()).toEqual([png.toString("base64"), overrideBytes].sort());
});
