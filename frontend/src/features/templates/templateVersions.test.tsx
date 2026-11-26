import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { useRecords } from "../../shared/api/client";
import { ProjectProvider } from "../projects/projectContext";
import { authenticatedRequest } from "../session/session";
import type { Branch, Version } from "./lifecycleTypes";
import { initialDraft, TemplateEditorPage } from "./templates";
import type { Template } from "./types";

vi.mock("../../shared/api/client", async (load) => ({ ...await load<typeof import("../../shared/api/client")>(), useRecords: vi.fn() }));
vi.mock("../session/session", () => ({ authenticatedRequest: vi.fn() }));
vi.mock("./templateCode", () => ({
  Code: ({ label, value }: { label: string; value: string }) => <textarea aria-label={label} value={value} readOnly />,
  TextContent: ({ label, value, change }: { label: string; value: string; change: (value: string) => void }) =>
    <input aria-label={label} value={value} onChange={(event) => change(event.target.value)} />,
}));

const session = { account: { id: "editor", email: "editor@example.test", platform_admin: true }, csrf_token: "test-token" };
const english: Template = {
  id: "welcome", name: "Welcome", key: "welcome", channel: "email",
  draft: { ...initialDraft(), subject: "English draft", layout: { template_id: "brand", version_id: null } },
  draft_revision: 4, updated_at: "2026-11-25T10:00:00Z", branch_id: "main-en", branch_name: "main",
  locale: "en", fallback_locale: "en", has_published_versions: true, primary_locale: "en", languages: ["en", "fr"],
  projects: [], project_count: 0, editable: true, manage_bindings: true,
};
const french: Template = { ...english, locale: "fr", branch_id: "main-fr", draft: { ...english.draft, subject: "French draft" } };
const base = "/templates/welcome";
const versions: Version[] = [
  { id: "english-experiment", branch_id: "test-en", branch_name: "experiment", locale: "en", number: 1, parent_version_id: null, draft_revision: 3, message: "", author: "editor", created_at: english.updated_at },
  { id: "english-main", branch_id: "main-en", branch_name: "main", locale: "en", number: 2, parent_version_id: null, draft_revision: 3, message: "", author: "editor", created_at: english.updated_at },
  { id: "french-main", branch_id: "main-fr", branch_name: "main", locale: "fr", number: 3, parent_version_id: null, draft_revision: 3, message: "", author: "editor", created_at: english.updated_at },
];
const branches: Branch[] = versions.map((head) => ({ id: head.branch_id, name: head.branch_name, locale: head.locale, draft_revision: 4, source_version_id: null, head }));

beforeEach(() => {
  vi.mocked(useRecords).mockReset();
  vi.mocked(useRecords).mockImplementation((path) => {
    const version = versions.find((version) => path === `${base}/versions/${version.id}`);
    let data: unknown;
    if (version) data = { ...version, content: { ...english.draft, preview_context: { name: version.locale } } };
    else if (path === base) data = english;
    else if (path === `${base}?branch_id=main-fr`) data = french;
    else if (path === `${base}/branches`) data = branches;
    else if (path === `${base}/versions`) data = versions;
    else if (path.startsWith(`${base}/deployments?`)) data = { rows: [] };
    else if (path === "/projects") data = [];
    else throw new Error(`Unexpected query: ${path}`);
    return { data: { data }, isPending: false, isFetchedAfterMount: true, refetch: vi.fn(async () => undefined) } as never;
  });
  vi.mocked(authenticatedRequest).mockReset();
  vi.mocked(authenticatedRequest).mockImplementation(async (_session, path) => {
    if (path === `${base}/layout-options`) return {
      layouts: [{ id: "brand", name: "Brand", fallback_locale: "en", versions: [{ id: "layout-pin", locale: "en", branch: "main", number: 5 }] }], targets: [],
    } as never;
    const version = versions.find((row) => path === `${base}/versions/${row.id}/preview`);
    return { rendered: version ? { subject: `Published ${version.id}`, html: "<p>Published email</p>", text: "Published email" } : null, errors: [], diagnostics: [] } as never;
  });
});

function mount() {
  render(<MemoryRouter initialEntries={[base]}><ProjectProvider accountId="editor"><Routes>
    <Route path="/templates/:templateId" element={<TemplateEditorPage session={session} />} />
  </Routes></ProjectProvider></MemoryRouter>);
}

function openPicker(name: string) {
  fireEvent.mouseDown(screen.getByRole("combobox", { name }));
}

async function choose(label: string) {
  fireEvent.click(await screen.findByText(label, { selector: ".ant-select-item-option-content" }));
}

// These interactions exercise several Ant Design dropdowns and debounced previews.
const editorInteractionTimeout = 30_000;

it("views different published snapshots in the Draft Editor and restores local text and the layout pin", async () => {
  mount();
  await screen.findByRole("option", { name: "en · main · v5" });
  fireEvent.change(screen.getByLabelText("Email subject"), { target: { value: "Edited locally" } });
  fireEvent.change(screen.getByRole("combobox", { name: "Layout version" }), { target: { value: "layout-pin" } });

  openPicker("Template version");
  expect(screen.queryByText("main · v3", { selector: ".ant-select-item-option-content" })).not.toBeInTheDocument();
  await choose("experiment · v1");
  expect(screen.getByRole("tab", { name: "Draft editor" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText("Viewing published · experiment · v1")).toBeVisible();
  expect(screen.queryByRole("textbox", { name: "Email subject" })).not.toBeInTheDocument();
  fireEvent.keyDown(window, { key: "s", ctrlKey: true });
  expect(await screen.findByRole("heading", { name: "Published english-experiment" })).toBeVisible();

  openPicker("Template version");
  await choose("main · v2");
  expect(await screen.findByRole("heading", { name: "Published english-main" })).toBeVisible();
  expect(authenticatedRequest).toHaveBeenCalledWith(session, `${base}/versions/english-main/preview`, "POST", { context: { name: "en" } });

  openPicker("Template version");
  await choose("Current draft");
  expect(screen.getByRole("textbox", { name: "Email subject" })).toHaveValue("Edited locally");
  expect(screen.getByRole("combobox", { name: "Layout version" })).toHaveValue("layout-pin");
  expect(screen.queryByText("Viewing published · main · v2")).not.toBeInTheDocument();
  expect(vi.mocked(authenticatedRequest).mock.calls.some((call) => call[2] === "PUT")).toBe(false);
}, editorInteractionTimeout);

it("protects unsaved edits on a language switch and lists published versions for the new language", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
  try {
    mount();
    fireEvent.change(screen.getByRole("textbox", { name: "Email subject" }), { target: { value: "Edited English draft" } });
    openPicker("Template version");
    await choose("main · v2");

    openPicker("Editing language");
    await choose("Français · fr");
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Viewing published · main · v2")).toBeVisible();

    openPicker("Editing language");
    await choose("Français · fr");
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("textbox", { name: "Email subject" })).toHaveValue("French draft");
    expect(screen.queryByText("Viewing published · main · v2")).not.toBeInTheDocument();

    openPicker("Template version");
    expect(screen.queryByText("main · v2", { selector: ".ant-select-item-option-content" })).not.toBeInTheDocument();
    await choose("main · v3");
    expect(await screen.findByRole("heading", { name: "Published french-main" })).toBeVisible();
    openPicker("Template version");
    await choose("Current draft");
    expect(screen.getByRole("textbox", { name: "Email subject" })).toHaveValue("French draft");
  } finally {
    confirm.mockRestore();
  }
}, editorInteractionTimeout);
