import { fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { DataFields, VariablesEditor, languageLabel } from "./templateFields";
import { TextContent } from "./templateInputs";

const schema = { type: "object", properties: { email: { type: "string" } }, required: ["email"] };
describe("template authoring controls", () => {
  it("selects a supported format while preserving the variable contract", async () => {
    const change = vi.fn();
    render(<VariablesEditor schema={schema} disabled={false} onChange={change} />);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Format email" }).closest(".ant-select")!.querySelector(".ant-select-selector")!);
    fireEvent.click(await screen.findByText("Email address"));
    expect(change).toHaveBeenLastCalledWith({ ...schema, properties: { email: { type: "string", format: "email" } } });
  });
  it("validates new variable names and adds no test data implicitly", () => {
    const change = vi.fn();
    render(<VariablesEditor schema={schema} disabled={false} onChange={change} />);
    fireEvent.change(screen.getByLabelText("New variable"), { target: { value: "email" } });
    expect(screen.getByRole("button", { name: "Add variable" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("New variable"), { target: { value: "first_name" } });
    fireEvent.click(screen.getByRole("button", { name: "Add variable" }));
    expect(change).toHaveBeenLastCalledWith({ ...schema, properties: { email: { type: "string" }, first_name: { type: "string" } } });
  });
  it("keeps unset, false, zero and empty strings as distinct test-data values", () => {
    const change = vi.fn();
    render(<DataFields schema={{ type: "object", properties: { count: { type: "integer" }, note: { type: "string" } } }} value={{ count: 0, note: "" }} onChange={change} disabled={false} />);
    expect(screen.getByLabelText("Test data count")).toHaveValue("0");
    expect(screen.getByRole("button", { name: "Unset note" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Unset count" }));
    expect(change).toHaveBeenLastCalledWith({ note: "" });
  });
  it("uses a date input for dates and exposes validation errors beside the field", () => {
    render(<DataFields schema={{ type: "object", properties: { birth_date: { type: "string", format: "date" } } }} value={{}} onChange={vi.fn()} disabled={false} errors={{ birth_date: "A date is required" }} />);
    expect(screen.getByLabelText("Test data birth_date")).toHaveAttribute("type", "date");
    expect(screen.getByText("A date is required")).toBeVisible();
  });
  it("renders named languages and tolerates legacy regional codes", () => {
    expect(languageLabel("uk")).toContain("Українська");
    expect(languageLabel("en")).toContain("English");
    expect(languageLabel("uk-12")).toContain("uk-12");
  });
});


it("inserts into the content field's current selection rather than the select's search input", () => {
  function Harness() {
    const [value, setValue] = useState("Hello world");
    const action = useRef<(value: string) => void>(() => undefined);
    return <><TextContent label="Subject" value={value} change={setValue} disabled={false} variables={["email"]} activate={(insert) => { action.current = insert; }} /><button onClick={() => action.current("{{ email }}")}>Insert into focused field</button></>;
  }
  render(<Harness />);
  const input = screen.getByRole("textbox", { name: "Subject" }) as HTMLInputElement;
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: "Welcome world" } });
  input.setSelectionRange(8, 13);
  fireEvent.click(screen.getByRole("button", { name: "Insert into focused field" }));
  expect(input).toHaveValue("Welcome {{ email }}");
});


it("treats a variable named constructor as absent until an explicit value is supplied", () => {
  const change = vi.fn();
  render(<DataFields schema={{ type: "object", properties: { constructor: { type: "string" } } }} value={{}} onChange={change} disabled={false} />);
  expect(screen.getByLabelText("Test data constructor")).toHaveValue("");
  expect(screen.queryByRole("button", { name: "Unset constructor" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Test data constructor"), { target: { value: "supplied" } });
  expect(change).toHaveBeenLastCalledWith({ constructor: "supplied" });
});

it("selects phone with an explicit version while preserving advanced constraints", async () => {
  const change = vi.fn();
  const contract = { type: "object", properties: { number: { type: "string", maxLength: 16, pattern: "^\\+" } } };
  render(<VariablesEditor schema={contract} disabled={false} onChange={change} />);
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "Format number" }).closest(".ant-select")!.querySelector(".ant-select-selector")!);
  fireEvent.click(await screen.findByText("Phone number (E.164)"));
  expect(change).toHaveBeenLastCalledWith({ ...contract, properties: { number: { ...contract.properties.number, format: "phone", "x-voxriva-phone-version": 1 } } });
});

it("explains international phone input and preserves the entered text", () => {
  const change = vi.fn();
  render(<DataFields schema={{ type: "object", properties: { phone: { type: "string", format: "phone", "x-voxriva-phone-version": 1 } } }} value={{}} onChange={change} disabled={false} />);
  const input = screen.getByLabelText("Test data phone");
  expect(input).toHaveAttribute("type", "tel");
  expect(input).toHaveAttribute("placeholder", "+12025550123");
  expect(input.getAttribute("title")).toContain("Region is never inferred");
  fireEvent.change(input, { target: { value: "+1 202 555 0123" } });
  expect(change).toHaveBeenLastCalledWith({ phone: "+1 202 555 0123" });
});
