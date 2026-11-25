import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Form, Input } from "antd";
import { expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { Editor } from "./adminForms";

it("preserves edited values and keeps the dialog open on a revision conflict", async () => {
  const close = vi.fn();
  const submit = vi.fn().mockRejectedValue(new ApiError(409, "Draft revision changed. Reload the saved draft."));
  render(<Editor title="Edit draft" close={close} submit={submit} initial={{ name: "Saved name" }}>
    <Form.Item name="name" label="Draft name"><Input /></Form.Item>
  </Editor>);
  fireEvent.change(screen.getByLabelText("Draft name"), { target: { value: "My unsaved work" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(screen.getByText("Draft revision changed. Reload the saved draft.")).toBeVisible());
  expect(screen.getByLabelText("Draft name")).toHaveValue("My unsaved work");
  expect(close).not.toHaveBeenCalled();
  expect(submit).toHaveBeenCalledWith({ name: "My unsaved work" });
});

it("prevents repeated submissions while a request is pending", async () => {
  let finish!: () => void;
  const pending = new Promise<void>((resolve) => { finish = resolve; });
  const submit = vi.fn().mockReturnValue(pending);
  const close = vi.fn();
  render(<Editor title="Publish" close={close} submit={submit}><span>Saved draft</span></Editor>);
  const save = screen.getByRole("button", { name: "Save" });
  fireEvent.click(save);
  await waitFor(() => expect(save).toHaveClass("ant-btn-loading"));
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  fireEvent.click(save);
  expect(submit).toHaveBeenCalledOnce();
  finish();
  await waitFor(() => expect(close).toHaveBeenCalledOnce());
});
