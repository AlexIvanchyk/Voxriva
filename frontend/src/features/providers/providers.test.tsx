import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ProvidersPage } from "./providers";

vi.mock("../../shared/api/client", () => ({
  errorMessage: () => "Failure",
  useRecords: (path: string) => {
    const revision = { id: "r1", number: 1, config: { host: "mailpit" }, configured_secrets: [], created_at: "2026-11-25T10:00:00Z" };
    const provider = { id: "local", name: "Local Mailpit", provider_type: "smtp", channel: "email", project_id: null, project_name: null, editable: true, latest: revision };
    const data = path === "/providers" ? [provider] : path.endsWith("/revisions") ? [revision] : [];
    return { data: { data }, error: null, isPending: false, refetch: vi.fn() };
  },
}));
const session = { account: { id: "admin", email: "admin@example.test", platform_admin: true }, csrf_token: "test" };

it.each(["Escape", "Close revisions"])("restores the original Revisions trigger after %s", async (close) => {
  render(<ProvidersPage session={session} />);
  const trigger = screen.getByRole("button", { name: "Revisions" });
  trigger.focus();
  fireEvent.click(trigger);
  const dialog = await screen.findByRole("dialog", { name: "Provider revisions · Local Mailpit" });
  await waitFor(() => expect(within(dialog).getByText("host:")).toBeVisible());
  if (close === "Escape") fireEvent.keyDown(dialog, { key: "Escape", keyCode: 27 });
  else fireEvent.click(within(dialog).getByRole("button", { name: close }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  await waitFor(() => expect(trigger).toHaveFocus());
});
