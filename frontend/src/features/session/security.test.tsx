import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { apiRequest } from "../../shared/api/client";
import { RecoveryCodes, SecondFactor, SecurityPage } from "./security";

const session = { account: { id: "fixture", email: "fixture@example.test", platform_admin: false }, csrf_token: "fixture-csrf" };

it("keeps invalid MFA proofs in the form without signing out the current session", async () => {
  const ended = vi.fn();
  window.addEventListener("voxriva-session-ended", ended);
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ detail: "Invalid or already used verification code" }, { status: 401 })));
  await expect(apiRequest("/api/v1/auth/mfa/disable", { method: "POST" })).rejects.toThrow("Invalid or already used");
  expect(ended).not.toHaveBeenCalled();
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ detail: "Sign in required" }, { status: 401 })));
  await expect(apiRequest("/api/v1/auth/mfa/disable", { method: "POST" })).rejects.toThrow("Sign in required");
  expect(ended).toHaveBeenCalledOnce();
  window.removeEventListener("voxriva-session-ended", ended);
});

it("shows an expired challenge and permits restarting sign-in without authentication", async () => {
  const signedIn = vi.fn(); const restart = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ detail: "Verification expired or unavailable. Sign in again." }, { status: 401 })));
  render(<MemoryRouter><SecondFactor challenge={{ mfa_required: true, challenge: "fictional", expires_in: 300, enrollment_required: false }} onSignIn={signedIn} restart={restart} /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("Authenticator or recovery code"), { target: { value: "123456" } });
  fireEvent.click(screen.getByRole("button", { name: "Verify" }));
  expect(await screen.findByText("Verification expired or unavailable. Sign in again.")).toBeInTheDocument();
  expect(signedIn).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Start sign-in again" }));
  expect(restart).toHaveBeenCalledOnce();
});

it("provides recovery code copy, download and acknowledgement", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined); const done = vi.fn();
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  render(<RecoveryCodes codes={["fictional-code-one", "fictional-code-two"]} done={done} />);
  fireEvent.click(screen.getByRole("button", { name: "Copy codes" }));
  expect(writeText).toHaveBeenCalledWith("fictional-code-one\nfictional-code-two");
  expect(await screen.findByText("Copied")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Download codes" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "I saved my recovery codes" }));
  expect(done).toHaveBeenCalledOnce();
});

it("hides self-service disable when the installation requires MFA", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ enabled: true, recovery_codes_remaining: 7, policy: "required" })));
  render(<MemoryRouter><SecurityPage session={session} /></MemoryRouter>);
  expect(await screen.findByText("Multi-factor authentication is enabled")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("button", { name: "Regenerate recovery codes" })).toBeInTheDocument());
  expect(screen.queryByRole("button", { name: "Disable MFA" })).not.toBeInTheDocument();
});
