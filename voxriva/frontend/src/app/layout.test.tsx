import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { Dashboard } from "./layout";

vi.mock("./routes", () => ({ DashboardRoutes: () => <h1>Template content</h1> }));
vi.mock("../features/projects/projectContext", () => ({ useProjectContext: () => ({ projects: [] }), canManage: () => false }));
const session = { account: { id: "viewer", email: "viewer@example.test", platform_admin: false }, csrf_token: "synthetic" };

it("closes the menu when selecting the already-active route and moves focus to content", async () => {
  render(<MemoryRouter initialEntries={["/templates"]}><Dashboard session={session} signOut={vi.fn()} /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "Menu" }));
  const dialog = await screen.findByRole("dialog", { name: "Navigation" });
  await waitFor(() => expect(within(dialog).getByRole("link", { name: "Templates" })).toBeVisible());
  expect(within(dialog).getByRole("link", { name: "API keys" })).toBeInTheDocument();
  expect(within(dialog).queryByRole("link", { name: "System Health" })).not.toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("link", { name: "Templates" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Navigation" })).not.toBeInTheDocument());
  await waitFor(() => expect(screen.getByRole("main")).toHaveFocus());
});
