import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiRequest, errorMessage } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("API failures", () => {
  it.each([
    [409, { detail: { message: "Draft revision changed", expected_revision: 3 } }, "Draft revision changed"],
    [422, { detail: [{ loc: ["body", "email"], msg: "Invalid email" }] }, "body.email: Invalid email"],
    [403, { detail: "Project administrator access required" }, "Project administrator access required"],
  ])("preserves HTTP %s details for the caller", async (status, body, message) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })));
    const failure = await apiRequest("/api/v1/templates").catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({ statusCode: status, details: body.detail, message });
    expect(errorMessage(failure)).toBe(message);
  });

  it("ends a session when an authenticated request expires", async () => {
    const expired = vi.fn();
    window.addEventListener("voxriva-session-ended", expired);
    try {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("expired", { status: 401 })));
      await expect(apiRequest("/api/v1/projects")).rejects.toMatchObject({ statusCode: 401 });
      expect(expired).toHaveBeenCalledOnce();
    } finally { window.removeEventListener("voxriva-session-ended", expired); }
  });

  it("keeps a failed sign-in separate from session expiry", async () => {
    const expired = vi.fn();
    window.addEventListener("voxriva-session-ended", expired);
    try {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("denied", { status: 401 })));
      await expect(apiRequest("/api/v1/auth/login")).rejects.toMatchObject({ statusCode: 401 });
      expect(expired).not.toHaveBeenCalled();
    } finally { window.removeEventListener("voxriva-session-ended", expired); }
  });

  it("handles empty successful responses without parsing JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(apiRequest("/api/v1/auth/logout")).resolves.toBeUndefined();
  });

  it("uses a recoverable message when the network fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network unavailable")));
    const failure = await apiRequest("/api/v1/projects").catch((error: unknown) => error);
    expect(errorMessage(failure)).toBe("Could not connect to Voxriva. Try again.");
  });
});
