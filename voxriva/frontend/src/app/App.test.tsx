import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import type { SystemStatus } from "../features/system/api";
import { App } from "./App";

const platformSession = {
  account: { id: "admin-1", email: "admin@example.test", platform_admin: true },
  csrf_token: "csrf-for-test",
};
const tenantSession = {
  account: { id: "tenant-1", email: "tenant@example.test", platform_admin: false },
  csrf_token: "tenant-csrf",
};
const timestamp = "2026-11-24T12:00:00Z";
const info = { name: "Voxriva", version: "0.1.0" };
const report: SystemStatus = {
  info,
  readiness: { status: "ready", checks: { api: "ready", postgres: "ready", redis: "ready" } },
  monitoring: {
    status: "current",
    snapshot: {
      observed_at: timestamp,
      containers: [
        { service: "redis", name: null, state: "missing", health: "unknown", restart_count: null, observed_at: timestamp },
        {
          service: "migrate", name: "voxriva-migrate-1", state: "completed",
          health: "not_configured", restart_count: 0, observed_at: timestamp,
        },
      ],
    },
  },
  snapshot_max_age_seconds: 12,
};

function mockDashboard(url: string, result: SystemStatus, session: typeof platformSession) {
  if (url.endsWith("/auth/session")) return Response.json(session);
  if (url.endsWith("/info")) return Response.json(info);
  if (url.endsWith("/readiness")) return Response.json(result.readiness);
  if (url.endsWith("/projects") || url.endsWith("/management-credentials")) return Response.json([]);
  if (url.endsWith("/system/status")) return Response.json(result);
  throw new Error(`Unexpected dashboard request: ${url}`);
}

function open(path: string, result: SystemStatus = report, session = platformSession) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => mockDashboard(url, result, session)));
  render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
}

it("renders the version and live readiness in Overview", async () => {
  open("/");
  expect(await screen.findByText("API version 0.1.0")).toBeInTheDocument();
  expect(screen.getByText("Connected")).toBeInTheDocument();
  expect(await screen.findAllByText("Ready")).toHaveLength(3);
  expect(screen.getByRole("link", { name: /System Health/ })).toHaveAttribute("href", "/system/health");
});

it("opens the container view from the Overview shortcut and highlights System Health", async () => {
  open("/");
  fireEvent.click(await screen.findByRole("link", { name: "View system health" }));

  expect(await screen.findByRole("heading", { name: "System Health" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "System Health" })).toHaveAttribute("aria-current", "page");
  expect(await screen.findByRole("row", { name: /voxriva-migrate-1.*Completed/ })).toBeInTheDocument();
});

it("shows API connectivity errors", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/auth/session") || url.endsWith("/projects")
    ? mockDashboard(url, report, platformSession) : new Response(null, { status: 502 })));
  render(<MemoryRouter><App /></MemoryRouter>);
  expect(await screen.findByText("API connection unavailable")).toBeInTheDocument();
  expect(screen.queryByText("Connected")).not.toBeInTheDocument();
});

it("distinguishes a missing container from a completed job without a health check", async () => {
  open("/system/health");
  const missing = await screen.findByRole("row", { name: /Redis.*Missing/ });
  expect(within(missing).getByText("Unknown")).toBeInTheDocument();
  const completed = screen.getByRole("row", { name: /voxriva-migrate-1.*Completed/ });
  expect(within(completed).getByText("No health check")).toBeInTheDocument();
  expect(within(completed).getByText("0")).toBeInTheDocument();
});

it("retains the last snapshot when the collector becomes stale", async () => {
  open("/system/health", { ...report, monitoring: { ...report.monitoring, status: "stale" } });
  expect(await screen.findByText("Container data is stale")).toBeInTheDocument();
  expect(screen.getByText("voxriva-migrate-1")).toBeInTheDocument();
});

it("shows unavailable monitoring before the first snapshot", async () => {
  open("/system/health", { ...report, monitoring: { status: "unavailable", snapshot: null } });
  expect(await screen.findByText("Container monitoring unavailable")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("shows the empty container list separately from unavailable monitoring", async () => {
  open("/system/health", { ...report, monitoring: {
    status: "current", snapshot: { observed_at: timestamp, containers: [] },
  } });
  expect(await screen.findByText("No containers were reported")).toBeInTheDocument();
});

it("requires sign-in and uses the dashboard request header", async () => {
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith("/auth/session")) return Response.json({ detail: "Sign in required" }, { status: 401 });
    if (url.endsWith("/auth/login")) {
      expect(new Headers(options?.headers).get("X-Voxriva-Client")).toBe("dashboard");
      return Response.json(platformSession);
    }
    return mockDashboard(url, report, platformSession);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<MemoryRouter><App /></MemoryRouter>);

  fireEvent.change(await screen.findByLabelText("Email"), { target: { value: platformSession.account.email } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "A synthetic password" } });
  fireEvent.click(screen.getByRole("button", { name: /Sign in/ }));
  expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledWith("/api/v1/auth/login", expect.objectContaining({
    method: "POST",
    body: JSON.stringify({ email: platformSession.account.email, password: "A synthetic password" }),
    headers: expect.any(Headers),
  }));
});

it("hides System Health for tenant users, including a direct dashboard link", async () => {
  open("/system/health", report, tenantSession);
  expect(await screen.findByText("Platform administrator access required")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "System Health" })).not.toBeInTheDocument();
});

it("shows only accessible projects and hides project creation from members", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/projects")
    ? Response.json([{ id: "project", name: "Northwind", role: "project_admin" }]) : mockDashboard(url, report, tenantSession)));
  render(<MemoryRouter initialEntries={["/projects"]}><App /></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "Northwind" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Create project" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Organizations" })).not.toBeInTheDocument();
});

const keyProject = { id: "project", name: "Storefront" };
const dev = { id: "dev", name: "Development", project: keyProject };
const prod = { id: "prod", name: "Production", project: keyProject };
const localKey = {
  id: "key-dev", name: "Local integration", prefix: "vxk_aaaaaaaa", environment_id: dev.id,
  expires_at: null, revoked_at: null,
};
const prodKey = {
  id: "key-prod", name: "Checkout production", prefix: "vxk_bbbbbbbb", environment_id: prod.id,
  expires_at: null, revoked_at: null,
};

it("opens API keys directly and searches without visiting nested resources", async () => {
  const fetcher = vi.fn(async (url: string) => url === "/api/v1/api-keys"
    ? Response.json({ environments: [dev, prod], keys: [localKey, prodKey] })
    : mockDashboard(url, report, platformSession));
  vi.stubGlobal("fetch", fetcher);
  render(<MemoryRouter><App /></MemoryRouter>);

  fireEvent.click(await screen.findByRole("link", { name: "API keys" }));
  expect(await screen.findByRole("heading", { name: "API keys" })).toBeInTheDocument();
  const localRow = (await screen.findByText(localKey.name)).closest("tr")!;
  expect(within(localRow).getByText(dev.name)).toBeInTheDocument();
  expect(within(localRow).getByText(keyProject.name)).toBeInTheDocument();
  const productionRow = screen.getByText(prodKey.name).closest("tr")!;
  expect(within(productionRow).getByText(prod.name)).toBeInTheDocument();

  fireEvent.change(screen.getByRole("textbox", { name: "Search keys" }), { target: { value: "VXK_BBB" } });
  expect(screen.getByText(prodKey.name)).toBeInTheDocument();
  expect(screen.queryByText(localKey.name)).not.toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => url.includes("/organizations"))).toBe(false);
});

it("preserves the environment filter for existing scoped links", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url === "/api/v1/api-keys"
    ? Response.json({ environments: [dev, prod], keys: [localKey, prodKey] })
    : url === "/api/v1/projects" ? Response.json([{ ...keyProject, role: "platform_admin" }])
    : mockDashboard(url, report, platformSession)));
  render(<MemoryRouter initialEntries={["/projects/project/environments/dev"]}><App /></MemoryRouter>);

  expect(await screen.findByText(localKey.name)).toBeInTheDocument();
  expect(screen.queryByText(prodKey.name)).not.toBeInTheDocument();
  expect(screen.getByText("Storefront / Development")).toBeInTheDocument();
});

it("issues a key in the selected environment and shows the secret only once", async () => {
  const key = "vxk_" + "a".repeat(43);
  let records: object[] = [];
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url === "/api/v1/api-keys") return Response.json({ environments: [dev, prod], keys: records });
    if (url === "/api/v1/projects/project/environments/prod/keys" && options?.method === "POST") {
      expect(new Headers(options.headers).get("X-CSRF-Token")).toBe(platformSession.csrf_token);
      expect(JSON.parse(String(options.body))).toEqual({ name: prodKey.name, expires_in_days: 90 });
      records = [prodKey];
      return Response.json({ ...prodKey, key }, { status: 201 });
    }
    return mockDashboard(url, report, platformSession);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<MemoryRouter initialEntries={["/api-keys"]}><App /></MemoryRouter>);

  fireEvent.click(await screen.findByRole("button", { name: "Create API key" }));
  // Wait on the title first: repeatedly computing accessible names over Ant
  // Design's transitioning modal tree can starve its pending form promises in
  // jsdom. Still verify the named dialog and its controls once it is mounted.
  await screen.findByText("Create API key", { selector: "h2" });
  const editor = screen.getByRole("dialog", { name: "Create API key" });
  fireEvent.change(within(editor).getByLabelText("Name"), { target: { value: prodKey.name } });
  fireEvent.mouseDown(within(editor).getByRole("combobox", { name: "Environment" }));
  const productionOption = await screen.findByText("Storefront / Production");
  fireEvent.click(productionOption);
  fireEvent.click(within(editor).getByRole("button", { name: "Create key" }));

  await screen.findByText("Copy your API key");
  const secret = screen.getByRole("dialog", { name: "Copy your API key" });
  expect(within(secret).getByText("Storefront / Production")).toBeInTheDocument();
  expect(within(secret).getByText(key)).toBeInTheDocument();
  fireEvent.click(within(secret).getByRole("button", { name: "Done" }));
  expect(screen.queryByText(key)).not.toBeInTheDocument();
  expect(await screen.findByText(prodKey.name)).toBeInTheDocument();
});


it("opens independent workspace sections without a global project selector", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url === "/api/v1/projects" ? Response.json([{ ...keyProject, role: "platform_admin" }]) : mockDashboard(url, report, platformSession)));
  render(<MemoryRouter initialEntries={["/projects"]}><App /></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "Projects" })).toBeInTheDocument();
  expect(await screen.findByRole("heading", { name: "Storefront" })).toBeInTheDocument();
  const nav = screen.getByRole("navigation", { name: "Main navigation" });
  expect(screen.queryByRole("combobox", { name: "Switch project" })).not.toBeInTheDocument();
  expect(within(nav).getByRole("link", { name: "Templates" })).toHaveAttribute("href", "/templates");
  for (const section of ["Environments", "Members"]) expect(within(nav).getByRole("link", { name: section })).toHaveAttribute("href", `/${section.toLowerCase()}`);
});

it("blocks an inaccessible project before requesting its members", async () => {
  const fetcher = vi.fn(async (url: string) => mockDashboard(url, report, tenantSession));
  vi.stubGlobal("fetch", fetcher);
  render(<MemoryRouter initialEntries={["/members?project=foreign"]}><App /></MemoryRouter>);
  expect(await screen.findByText(/This project is unavailable/)).toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => url.endsWith("/members"))).toBe(false);
});


it("shows intentionally disabled monitoring while retaining dependency readiness", async () => {
  open("/system/health", { ...report, monitoring: { status: "disabled", snapshot: null } });
  expect(await screen.findByText("Container monitoring disabled")).toBeInTheDocument();
  expect(screen.getAllByText("Ready")).toHaveLength(3);
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  for (const message of ["Container monitoring unavailable", "Container data is stale", "Last snapshot", "API connection unavailable"]) {
    expect(screen.queryByText(message)).not.toBeInTheDocument();
  }
});


it("shows recipient emails and searches across notification pages", async () => {
  const fetcher = vi.fn(async (url: string) => {
    if (url.includes("/notifications?")) return Response.json({ items: [{
      id: "delivery-1", channel: "email", recipient_email: "recipient@example.test", recipient_mask: "r***@***",
      status: "sent", created_at: timestamp,
      resolution: { template_name: "Welcome", template_key: "welcome", project_name: "Demo", environment_name: "Dev", branch_name: "main", template_version: 1, resolved_locale: "en", provider_name: "SMTP", provider_revision: 1 },
    }], total: 51, limit: 25, offset: 25 });
    if (url.endsWith("/environments")) return Response.json([]);
    return mockDashboard(url, report, platformSession);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<MemoryRouter initialEntries={["/notifications?page=2&status=sent"]}><App /></MemoryRouter>);
  expect(await screen.findByText("recipient@example.test")).toBeInTheDocument();
  const input = screen.getByLabelText("Search recipient email");
  fireEvent.change(input, { target: { value: "example.test" } });
  fireEvent.keyDown(input, { key: "Enter", code: "Enter", keyCode: 13 });
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes("recipient_email=example.test") && url.includes("offset=0") && url.includes("status=sent"))).toBe(true));
});
