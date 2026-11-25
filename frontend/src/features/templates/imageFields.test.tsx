import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { isolatedHtml } from "../../shared/lib/previewHtml";
import { ImageUpload, imageSchema, sampleImage } from "./imageFields";

describe("Image variables", () => {
  it("uses a valid object contract and generates only explicit fixture data", () => {
    expect(imageSchema.type).toBe("object");
    expect(imageSchema["x-voxriva-image"]).toBe(1);
  });
  it("reads actual local image bytes and rejects unsupported uploads", async () => {
    const change = vi.fn(); render(<ImageUpload label="Test image upload" onChange={change} />);
    const file = new File(["bad"], "logo.svg", { type: "image/svg+xml" });
    fireEvent.change(screen.getByLabelText("Test image upload"), { target: { files: [file] } });
    expect(screen.getByText(/Choose PNG/)).toBeVisible(); expect(change).not.toHaveBeenCalled();
    const image = new File(["fictional"], "logo.png", { type: "image/png" });
    image.arrayBuffer = async () => new TextEncoder().encode("fictional").buffer;
    fireEvent.change(screen.getByLabelText("Test image upload"), { target: { files: [image] } });
    await waitFor(() => expect(change).toHaveBeenCalledWith({ media_type: "image/png", content_base64: btoa("fictional") }));
  });
  it("resolves only bounded CID identities while retaining preview isolation", () => {
    const cid = "a".repeat(64) + "@images.voxriva";
    const result = isolatedHtml(`<img src="cid:${cid}" onerror="alert(1)"><img src="https://private.test/image"><script>alert(1)</script>`, [{ ...sampleImage, cid }]);
    expect(result).toContain(`src="data:image/png;base64,${sampleImage.content_base64}"`);
    expect(result).not.toContain("onerror"); expect(result).not.toContain("https://private.test"); expect(result).not.toContain("<script>");
    expect(result).toContain("default-src 'none'");
  });
});
