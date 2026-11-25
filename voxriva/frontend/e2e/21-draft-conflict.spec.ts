import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";
import { createProject, createTemplate, editCode, setup } from "./support/compose";

setup();

test("two editor tabs reject a stale draft save without losing local edits or overwriting the winner", async ({ page, context }) => {
  await createProject(page, "Two-tab draft conflict");
  const templateId = await createTemplate(page, "Concurrent editor welcome");
  const endpoint = `/api/v1/templates/${templateId}`;
  const draftUrl = new URL(`${endpoint}/draft`, page.url()).href;
  const originalResponse = await page.request.get(endpoint);
  expect(originalResponse.ok(), await originalResponse.text()).toBeTruthy();
  const original = await originalResponse.json();
  const winningSubject = "First tab saved this synthetic subject";
  const localSubject = "Second tab still owns these unsaved synthetic edits";
  const revision = (tab: Page, number: number) => tab.getByText(`Revision ${number} · Manual save · Ctrl / ⌘ S`, { exact: true });
  const saveButton = (tab: Page) => tab.getByRole("button", { name: /^(?:loading )?Save draft$/ });
  const second = await context.newPage();

  try {
    // A new tab shares the authenticated browser session, but has independent
    // editor state. Both tabs load the same original revision before either saves.
    await second.goto(`/templates/${templateId}`);
    await expect(second.getByRole("heading", { name: "Concurrent editor welcome", exact: true })).toBeVisible();
    await expect(revision(page, original.draft_revision)).toBeVisible();
    await expect(revision(second, original.draft_revision)).toBeVisible();
    await editCode(page, "Email subject", winningSubject);
    await editCode(second, "Email subject", localSubject);
    await expect(page.getByText("Unsaved changes", { exact: true })).toBeVisible();
    await expect(second.getByText("Unsaved changes", { exact: true })).toBeVisible();

    const [accepted] = await Promise.all([
      page.waitForResponse((response) => response.request().method() === "PUT" && response.url() === draftUrl),
      saveButton(page).click(),
    ]);
    expect(accepted.status()).toBe(200);
    expect(accepted.request().postDataJSON()).toMatchObject({
      expected_revision: original.draft_revision,
      branch_id: original.branch_id,
      draft: { subject: winningSubject },
    });
    const saved = await accepted.json();
    expect(saved.draft_revision).toBe(original.draft_revision + 1);
    expect(saved.draft.subject).toBe(winningSubject);
    await expect(revision(page, saved.draft_revision)).toBeVisible();
    await expect(page.getByText("Saved draft", { exact: true })).toBeVisible();

    // This is the actual editor PUT against the live backend, not an injected
    // error or a concurrent deployment request. Its original revision is stale.
    await expect(revision(second, original.draft_revision)).toBeVisible();
    const [rejected] = await Promise.all([
      second.waitForResponse((response) => response.request().method() === "PUT" && response.url() === draftUrl),
      saveButton(second).click(),
    ]);
    expect(rejected.status()).toBe(409);
    expect(rejected.request().postDataJSON()).toMatchObject({
      expected_revision: original.draft_revision,
      branch_id: original.branch_id,
      draft: { subject: localSubject },
    });
    const conflict = "Draft changed in another editor. Copy your edits before reloading.";
    expect(await rejected.json()).toEqual({ detail: conflict });
    await expect(second.getByRole("alert").filter({ hasText: conflict })).toBeVisible();
    await expect(second.getByRole("textbox", { name: "Email subject", exact: true })).toHaveValue(localSubject);
    await expect(second.getByText("Unsaved changes", { exact: true })).toBeVisible();
    await expect(revision(second, original.draft_revision)).toBeVisible();
    await expect(saveButton(second)).toBeEnabled();

    const persistedResponse = await second.request.get(endpoint);
    expect(persistedResponse.ok(), await persistedResponse.text()).toBeTruthy();
    const persisted = await persistedResponse.json();
    expect(persisted.draft_revision).toBe(saved.draft_revision);
    expect(persisted.draft.subject).toBe(winningSubject);
    expect(persisted.branch_id).toBe(original.branch_id);

    // Reload is an explicit discard operation: conflict handling itself retained
    // the local draft, and the dirty editor still warns before it is discarded.
    let confirmedDiscard = false;
    second.once("dialog", async (dialog) => {
      expect(dialog.type()).toBe("beforeunload");
      confirmedDiscard = true;
      await dialog.accept();
    });
    await second.reload();
    expect(confirmedDiscard).toBe(true);
    await expect(second.getByRole("textbox", { name: "Email subject", exact: true })).toHaveValue(winningSubject);
    await expect(revision(second, saved.draft_revision)).toBeVisible();
    await expect(second.getByText("Saved draft", { exact: true })).toBeVisible();
    await expect(second.getByRole("alert").filter({ hasText: conflict })).toHaveCount(0);
    await expect(saveButton(second)).toBeDisabled();
    const afterReload = await second.request.get(endpoint);
    expect(afterReload.ok(), await afterReload.text()).toBeTruthy();
    const final = await afterReload.json();
    expect(final.draft_revision).toBe(saved.draft_revision);
    expect(final.draft.subject).toBe(winningSubject);
  } finally {
    await second.close();
  }
});
