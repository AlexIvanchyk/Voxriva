import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { SetupSteps } from "./SetupSteps";

const context = vi.hoisted(() => ({ role: "viewer", empty: false }));
vi.mock("../projects/projectContext", () => ({
  useProjectContext: () => ({ projects: context.empty ? [] : [{ id: "demo", name: "Demo", role: context.role }], pending: false, error: null, refresh: vi.fn() }),
  canEdit: (project: { role: string }) => ["project_admin", "template_editor"].includes(project.role),
  canManage: (project: { role: string }) => project.role === "project_admin",
}));
vi.mock("../../shared/api/client", () => ({ useRecords: () => ({ data: { data: [] }, isPending: false, error: null, refetch: vi.fn() }) }));
it("offers an empty installation administrator all five setup destinations", () => {
  context.empty = true;
  render(<MemoryRouter><SetupSteps platformAdmin /></MemoryRouter>);
  expect(screen.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual(["/projects", "/environments", "/providers", "/templates", "/deployments"]);
});
it("does not offer management actions to a template editor", () => {
  context.empty = false; context.role = "template_editor";
  render(<MemoryRouter><SetupSteps platformAdmin={false} /></MemoryRouter>);
  expect(screen.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual(["/projects", "/templates"]);
  expect(screen.getAllByText(/Ask a project administrator/)).toHaveLength(3);
});
it("does not show setup actions to a viewer", () => {
  context.empty = false; context.role = "viewer";
  render(<MemoryRouter><SetupSteps platformAdmin={false} /></MemoryRouter>);
  expect(screen.queryByRole("region", { name: "Get started" })).not.toBeInTheDocument();
});
