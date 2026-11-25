import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { QueryContent } from "./QueryContent";

it("shows empty content only after a successful request and provides retry on failure", () => {
  const refetch = vi.fn(async () => undefined);
  const view = render(<QueryContent query={{ isPending: true, error: null, refetch }}><p>No templates yet</p></QueryContent>);
  expect(screen.getByRole("status", { name: "Loading results" })).toBeVisible();
  expect(screen.queryByText("No templates yet")).not.toBeInTheDocument();
  view.rerender(<QueryContent query={{ isPending: false, error: new Error("timeout"), refetch }}><p>No templates yet</p></QueryContent>);
  expect(screen.getByText("Could not load results")).toBeVisible();
  expect(screen.queryByText("No templates yet")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(refetch).toHaveBeenCalledOnce();
  view.rerender(<QueryContent query={{ isPending: false, error: null, refetch }}><p>No templates yet</p></QueryContent>);
  expect(screen.getByText("No templates yet")).toBeVisible();
});
