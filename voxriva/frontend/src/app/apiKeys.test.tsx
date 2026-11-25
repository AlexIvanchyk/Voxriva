import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { App } from "./App";

const session = { account: { id: "viewer", email: "viewer@example.test", platform_admin: false }, csrf_token: "synthetic-csrf" };
const project = { id: "readable", name: "Fictional Readable", role: "viewer" };
function base(url: string) {
  if (url.endsWith("/auth/session")) return Response.json(session);
  if (url.endsWith("/projects")) return Response.json([project]);
  if (url.endsWith("/api-keys")) return Response.json({ environments: [], keys: [] });
  return Response.json({});
}

it("lets a viewer manage their read credentials without offering delivery or write authority", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/management-credentials") ? Response.json([]) : base(url)));
  render(<MemoryRouter initialEntries={["/api-keys"]}><App /></MemoryRouter>);
  expect(await screen.findByRole("link", { name: "API keys" })).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Create API key" }));
  const dialog = await screen.findByRole("dialog", { name: "Create API key" });
  expect(within(dialog).queryByRole("combobox", { name: "Environment" })).not.toBeInTheDocument();
  fireEvent.mouseDown(within(dialog).getByRole("combobox", { name: "Template permissions" }));
  expect((await screen.findByText("Read and write templates")).closest(".ant-select-item-option")).toHaveClass("ant-select-item-option-disabled");
  expect(within(dialog).getByRole("spinbutton", { name: "Expires in days" })).toHaveValue("30");
});

it("keeps a failed MCP list visible as an error and retries without claiming an empty inventory", async () => {
  let attempts = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/management-credentials")
    ? ++attempts === 1 ? Response.json({ detail: "Credential list unavailable" }, { status: 503 }) : Response.json([])
    : base(url)));
  render(<MemoryRouter initialEntries={["/api-keys"]}><App /></MemoryRouter>);
  expect(await screen.findByText(/Template \/ MCP keys: Credential list unavailable/)).toBeInTheDocument();
  expect(screen.queryByText("No API keys yet")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Retry MCP keys" }));
  expect(await screen.findByText("No API keys yet")).toBeInTheDocument();
  expect(attempts).toBe(2);
});

it("retains access to revoke an owned MCP credential after all project memberships are removed", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/projects") ? Response.json([])
    : url.endsWith("/management-credentials") ? Response.json([{ id: "owned-credential", name: "Former project key", project_ids: ["former-project"], scopes: ["templates:read"], expires_at: "2099-01-01T00:00:00Z", revoked_at: null, created_at: "2026-11-25T00:00:00Z" }]) : base(url)));
  render(<MemoryRouter initialEntries={["/api-keys"]}><App /></MemoryRouter>);
  expect(await screen.findByRole("link", { name: "API keys" })).toBeInTheDocument();
  const row = await screen.findByRole("row", { name: /Former project key/ });
  expect(within(row).getByRole("button", { name: "Revoke" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Create API key" })).not.toBeInTheDocument();
});
