import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ApiError } from "../../shared/api/client";
import { authenticatedRequest } from "../session/session";
import { DraftEditor } from "./draftEditor";
import type { Template } from "./types";

vi.mock("../session/session", () => ({ authenticatedRequest: vi.fn() }));
vi.mock("./templateCode", () => ({
  Code: ({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) => <textarea aria-label={label} value={value} onChange={(event) => onChange(event.target.value)} />,
  TextContent: ({ label, value, change }: { label: string; value: string; change: (value: string) => void }) => <input aria-label={label} value={value} onChange={(event) => change(event.target.value)} />,
}));

it("keeps a dirty draft after a concurrent save conflict and sends its original revision", async () => {
  const draft = { contract_version: 1, subject: "", text: "", html: "", title: "", body: "", data: {}, variable_schema: { type: "object", properties: {} }, runtime_defaults: {}, preview_context: {}, scenarios: {} };
  const item: Template = { id: "welcome", name: "Welcome", key: "welcome", channel: "email", draft, draft_revision: 4, updated_at: "2026-11-25T10:00:00Z", branch_id: "main-en", branch_name: "main", locale: "en", fallback_locale: "en", has_published_versions: false, primary_locale: "en", languages: ["en"], projects: [], project_count: 0, editable: true, manage_bindings: true };
  const session = { account: { id: "editor", email: "editor@example.test", platform_admin: true }, csrf_token: "synthetic-csrf" };
  const saved = vi.fn(), dirty = vi.fn();
  vi.mocked(authenticatedRequest).mockImplementation(async (_session, path) => {
    if (path.endsWith("/draft")) throw new ApiError(409, "Draft changed. Reload before saving.");
    return { rendered: null, errors: [], diagnostics: [] } as never;
  });
  render(<DraftEditor item={item} session={session} editable path="/templates/welcome" onDirty={dirty} onSaved={saved} />);
  expect(screen.getByRole("button", { name: "Save draft" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Email subject"), { target: { value: "My unsaved subject" } });
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  expect(await screen.findByText("Draft changed. Reload before saving.")).toBeVisible();
  expect(screen.getByLabelText("Email subject")).toHaveValue("My unsaved subject");
  await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(true));
  expect(saved).not.toHaveBeenCalled();
  expect(authenticatedRequest).toHaveBeenCalledWith(session, "/templates/welcome/draft", "PUT", {
    draft: { ...draft, subject: "My unsaved subject" }, expected_revision: 4, branch_id: "main-en",
  });
});

function editor() {
  const draft = { contract_version: 1, subject: "", text: "", html: "", title: "", body: "", data: {}, variable_schema: { type: "object", properties: {} }, runtime_defaults: {}, preview_context: {}, scenarios: {} };
  const item: Template = { id: "welcome", name: "Welcome", key: "welcome", channel: "email", draft, draft_revision: 4, updated_at: "2026-11-25T10:00:00Z", branch_id: "main-en", branch_name: "main", locale: "en", fallback_locale: "en", has_published_versions: false, primary_locale: "en", languages: ["en"], projects: [], project_count: 0, editable: true, manage_bindings: true };
  const session = { account: { id: "editor", email: "editor@example.test", platform_admin: true }, csrf_token: "synthetic-csrf" };
  const onSaved = vi.fn(async () => undefined);
  vi.mocked(authenticatedRequest).mockReset();
  return { item, session, onSaved, mount: () => render(<DraftEditor item={item} session={session} editable path="/templates/welcome" onDirty={vi.fn()} onSaved={onSaved} />) };
}

it("confirms a committed timeout snapshot without losing edits made while saving", async () => {
  const { item, mount, onSaved } = editor();
  let rejectSave!: (error: Error) => void;
  vi.mocked(authenticatedRequest).mockImplementation(async (_session, path, method) => {
    if (method === "PUT") return await new Promise((_resolve, reject) => { rejectSave = reject; });
    if (path.includes("?branch_id=")) return { ...item, draft_revision: 5, draft: { ...item.draft, subject: "Snapshot" } } as never;
    return { rendered: null, errors: [], diagnostics: [] } as never;
  });
  mount();
  expect(screen.getByRole("slider", { name: "Editor width" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Email subject"), { target: { value: "Snapshot" } });
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  expect(screen.getByRole("button", { name: "Save draft" })).toHaveAttribute("aria-busy", "true");
  fireEvent.change(screen.getByLabelText("Email subject"), { target: { value: "Newer local work" } });
  rejectSave(new Error("timeout"));
  expect(await screen.findByText("Snapshot saved. Your newer edits remain unsaved.")).toBeVisible();
  expect(screen.getByLabelText("Email subject")).toHaveValue("Newer local work");
  expect(screen.getByText(/Revision 5/)).toBeInTheDocument();
  expect(onSaved).toHaveBeenCalledOnce();
  await waitFor(() => expect(screen.getByRole("button", { name: "Save draft" })).toHaveAttribute("aria-busy", "false"));
  expect(vi.mocked(authenticatedRequest).mock.calls.filter((call) => call[2] === "PUT")).toHaveLength(1);
});

it("blocks a new snapshot until an unknown write is checked and retries only the original revision", async () => {
  const { item, mount } = editor();
  let reads = 0, writes = 0;
  vi.mocked(authenticatedRequest).mockImplementation(async (_session, path, method) => {
    if (method === "PUT") { if (++writes === 1) throw new Error("timeout"); throw new ApiError(409, "Already committed"); }
    if (path.includes("?branch_id=")) { if (++reads === 1) throw new Error("offline"); return { ...item, draft_revision: 5, draft: { ...item.draft, subject: "Snapshot" } } as never; }
    return { rendered: null, errors: [], diagnostics: [] } as never;
  });
  mount();
  fireEvent.change(screen.getByLabelText("Email subject"), { target: { value: "Snapshot" } });
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  expect(await screen.findByText(/Could not verify the save result/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Save draft" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Email subject"), { target: { value: "Keep me" } });
  fireEvent.click(screen.getByRole("button", { name: "Retry same snapshot" }));
  expect(await screen.findByText("Snapshot saved. Your newer edits remain unsaved.")).toBeVisible();
  const calls = vi.mocked(authenticatedRequest).mock.calls.filter((call) => call[2] === "PUT");
  expect(calls).toHaveLength(2);
  expect(calls[0][3]).toEqual(calls[1][3]);
  expect(calls[1][3]).toMatchObject({ expected_revision: 4, draft: { subject: "Snapshot" } });
  expect(screen.getByLabelText("Email subject")).toHaveValue("Keep me");
});

it("preserves local work and the original revision when reconciliation finds someone else's draft", async () => {
  const { item, mount, onSaved } = editor();
  vi.mocked(authenticatedRequest).mockImplementation(async (_session, path, method) => {
    if (method === "PUT") throw new Error("timeout");
    if (path.includes("?branch_id=")) return { ...item, draft_revision: 6, draft: { ...item.draft, subject: "Other author" } } as never;
    return { rendered: null, errors: [], diagnostics: [] } as never;
  });
  mount();
  fireEvent.change(screen.getByLabelText("Email subject"), { target: { value: "Local work" } });
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  expect(await screen.findByText(/The server draft changed/)).toBeVisible();
  expect(screen.getByLabelText("Email subject")).toHaveValue("Local work");
  expect(screen.getByText(/Revision 4/)).toBeInTheDocument();
  expect(onSaved).not.toHaveBeenCalled();
});

it("does not misreport a confirmed save when refreshing page details fails", async () => {
  const { item, mount, onSaved } = editor();
  onSaved.mockRejectedValue(new Error("refresh failed"));
  vi.mocked(authenticatedRequest).mockImplementation(async (_session, _path, method) => method === "PUT" ? { ...item, draft_revision: 5 } as never : { rendered: null, errors: [], diagnostics: [] } as never);
  mount();
  fireEvent.change(screen.getByLabelText("Email subject"), { target: { value: "Saved" } });
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  expect(await screen.findByText(/your saved draft is confirmed/)).toBeVisible();
  expect(screen.getByText("Saved draft")).toBeVisible();
  expect(screen.queryByText("Could not connect to Voxriva. Try again.")).not.toBeInTheDocument();
});

it("preserves fixture data when bounded example generation fails", async () => {
  const { item, mount } = editor();
  item.draft.variable_schema = { type: "object", properties: { phone: { type: "string" } } };
  item.draft.preview_context = { phone: "Keep my unsaved fixture" };
  vi.mocked(authenticatedRequest).mockResolvedValue({ rendered: null, errors: [{ path: ["variable_schema"], code: "example", message: "Supply a valid schema example." }], diagnostics: [] } as never);
  mount();
  fireEvent.click(screen.getByRole("tab", { name: "Test data" }));
  fireEvent.click(screen.getByRole("button", { name: "Generate example" }));
  expect(await screen.findByText("Supply a valid schema example.")).toBeVisible();
  expect(screen.getByLabelText("Test data phone")).toHaveValue("Keep my unsaved fixture");
  expect(authenticatedRequest).toHaveBeenCalledWith(expect.anything(), "/templates/welcome/preview", "POST", { draft: item.draft, generate_example: true });
});
