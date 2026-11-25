import { createHash } from "node:crypto";
import { expect, test } from "@playwright/test";
import { compose, editCode, setup, signIn } from "./support/compose";

setup();

test("session expiry during editing rejects the save and restores only the persisted draft after sign-in", async ({ page, request }) => {
  const session = await (await page.request.get("/api/v1/auth/session")).json();
  const headers = { "X-CSRF-Token": session.csrf_token };
  async function create(path: string, data: object) {
    const response = await page.request.post(`/api/v1${path}`, { headers, data });
    expect(response.status(), await response.text()).toBe(201);
    return response.json();
  }
  const project = await create("/projects", { name: "Session expiry isolation" });
  const savedSubject = "Persisted before session expiry";
  const unsavedSubject = "Unsaved private edit after session expiry";
  const template = await create("/templates", {
    name: "Session expiry draft", key: "session-expiry-draft", channel: "email", project_ids: [project.id],
    draft: {
      subject: savedSubject, text: "Synthetic session expiry fixture",
      variable_schema: { type: "object", properties: {}, additionalProperties: false }, preview_context: {},
    },
  });
  const editorUrl = new URL(`/templates/${template.id}?branch=${template.branch_id}`, page.url()).href;
  await page.goto(editorUrl);
  await expect(page.getByRole("textbox", { name: "Email subject", exact: true })).toHaveValue(savedSubject);
  await editCode(page, "Email subject", unsavedSubject);
  await expect(page.getByText("Unsaved changes", { exact: true })).toBeVisible();
  // Complete the debounced preview before expiring the session, so the protected
  // action under test is Save rather than an incidental background request.
  await expect(page.getByRole("region", { name: "Live preview" }).getByText(unsavedSubject, { exact: true })).toBeVisible();

  const cookie = (await page.context().cookies()).find((item) => item.name === "voxriva_session" || item.name === "__Host-voxriva_session");
  expect(cookie).toBeDefined();
  const tokenHash = createHash("sha256").update(cookie!.value).digest("hex");
  // compose() refuses projects outside the isolated voxriva-test-* namespace.
  // Only this browser's session is changed; other test sessions remain valid.
  const expired = compose("exec", "-T", "postgres", "psql", "-U", "voxriva", "-d", "voxriva", "-Atc",
    `WITH expired AS (UPDATE dashboard_sessions SET expires_at=now()-interval '1 minute' WHERE token_hash='${tokenHash}' RETURNING 1) SELECT count(*) FROM expired`);
  expect(expired.trim()).toBe("1");

  const [rejectedSave] = await Promise.all([
    page.waitForResponse((response) => response.request().method() === "PUT" && new URL(response.url()).pathname === `/api/v1/templates/${template.id}/draft`),
    page.getByRole("button", { name: /^(?:loading )?Save draft$/ }).click(),
  ]);
  expect(rejectedSave.request().postDataJSON().draft.subject).toBe(unsavedSubject);
  expect(rejectedSave.status()).toBe(401);
  expect(await rejectedSave.json()).toEqual({ detail: "Sign in required" });
  await expect(page).toHaveURL(new URL("/sign-in", editorUrl).href);
  await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main navigation" })).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "Email subject", exact: true })).toHaveCount(0);

  const expiredHeaders = { Cookie: `${cookie!.name}=${cookie!.value}` };
  expect((await request.get("/api/v1/auth/session", { headers: expiredHeaders })).status()).toBe(401);
  // Security contract: expiry unmounts the privileged editor and discards its
  // in-memory unsaved draft. Sign-in restores the route, not unsaved contents.
  await signIn(page, process.env.VOXRIVA_TEST_EMAIL!, process.env.VOXRIVA_TEST_PASSWORD!);
  await expect(page).toHaveURL(editorUrl);
  await expect(page.getByRole("textbox", { name: "Email subject", exact: true })).toHaveValue(savedSubject);
  await expect(page.getByText("Saved draft", { exact: true })).toBeVisible();
  await expect(page.getByText("Unsaved changes", { exact: true })).toHaveCount(0);
  const persisted = await (await page.request.get(`/api/v1/templates/${template.id}?branch_id=${template.branch_id}`)).json();
  expect(persisted.draft.subject).toBe(savedSubject);
  expect(persisted.draft_revision).toBe(template.draft_revision);
  expect((await request.get("/api/v1/auth/session", { headers: expiredHeaders })).status()).toBe(401);
});
