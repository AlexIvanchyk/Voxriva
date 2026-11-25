import { render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { SessionGate } from "./session";

function Destination() {
  const location = useLocation();
  return <output>{location.pathname + location.search}</output>;
}

it.each([
  ["/templates/shared?branch=synthetic", "/templates/shared?branch=synthetic"],
  ["/notifications?page=2&status=sent", "/notifications?page=2&status=sent"],
  ["https://external.example.test", "/"],
  ["//external.example.test", "/"],
  [undefined, "/"],
])("preserves the safe return route when authentication completes on sign-in (%s)", async (returnTo, destination) => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({
    account: { id: "synthetic", email: "session@example.test", platform_admin: false },
    csrf_token: "synthetic-csrf",
  })));
  render(<MemoryRouter initialEntries={[{ pathname: "/sign-in", state: { returnTo } }]}>
    <SessionGate>{() => <Destination />}</SessionGate>
  </MemoryRouter>);
  expect(await screen.findByText(destination, { selector: "output" })).toBeInTheDocument();
});
