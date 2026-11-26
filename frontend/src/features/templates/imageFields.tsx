import { Alert, Button, Input, InputNumber, Modal, Select, Space } from "antd";
import { useState } from "react";
import type { Schema, Value } from "./templateFields";

export type ImageValue = { media_type: string; content_base64: string };
export const imageSchema: Schema = { type: "object", "x-voxriva-image": 1, properties: { media_type: { type: "string", enum: ["image/png", "image/jpeg", "image/webp"] }, content_base64: { type: "string", maxLength: 349528 } }, required: ["media_type", "content_base64"], additionalProperties: false };
export const sampleImage: ImageValue = { media_type: "image/png", content_base64: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=" };
export function ImageUpload({ value, onChange, disabled, label }: { value?: Value; onChange: (value: ImageValue) => void; disabled?: boolean; label: string }) {
  const [error, setError] = useState("");
  const image = value && typeof value === "object" && !Array.isArray(value) && typeof value.content_base64 === "string" && value.content_base64.length <= 349528 && /^[a-z0-9+/=]+$/i.test(value.content_base64) && ["image/png", "image/jpeg", "image/webp"].includes(String(value.media_type)) ? value : null;
  return <Space direction="vertical"><input aria-label={label} type="file" accept="image/png,image/jpeg,image/webp" disabled={disabled} onChange={async (event) => {
    const file = event.target.files?.[0]; event.target.value = ""; if (!file) return;
    if (file.size > 262144 || !["image/png", "image/jpeg", "image/webp"].includes(file.type)) { setError("Choose PNG, JPEG or WebP up to 256 KiB."); return; }
    try { const bytes = new Uint8Array(await file.arrayBuffer()); let binary = ""; for (const byte of bytes) binary += String.fromCharCode(byte); onChange({ media_type: file.type, content_base64: btoa(binary) }); setError(""); } catch { setError("Could not read image."); }
  }} />{image && <img alt="Selected image" style={{ maxWidth: 180, maxHeight: 100 }} src={`data:${image.media_type};base64,${image.content_base64}`} />}{error && <Alert type="error" message={error} />}<small>PNG, JPEG, WebP · 256 KiB · 4096 px per side · 4 million pixels. Server validates decoded content on preview/save.</small></Space>;
}
export function InsertImage({ images, inheritedImages = [], variables, defaults, insert, change, validate }: { images: Record<string, ImageValue>; inheritedImages?: string[]; variables: string[]; defaults: Record<string, Value>; insert: (html: string) => void; change: (images: Record<string, ImageValue>) => void; validate: (image: ImageValue) => Promise<ImageValue> }) {
  const [open, setOpen] = useState(false); const [selected, setSelected] = useState(""); const [upload, setUpload] = useState<ImageValue>(); const [alt, setAlt] = useState(""); const [width, setWidth] = useState<number | null>(null); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const escape = (value: string) => value.replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll("{", "&#123;").replaceAll("}", "&#125;");
  return <><Button size="small" onMouseDown={(e) => e.preventDefault()} onClick={() => { setOpen(true); setError(""); }}>Insert image</Button><Modal title="Insert image" open={open} confirmLoading={busy} okText="Insert image" onCancel={() => setOpen(false)} onOk={async () => {
    setBusy(true); setError(""); try {
      let src = selected;
      if (upload) { const image = await validate(upload); const name = `image_${crypto.randomUUID().replaceAll("-", "")}`; change({ ...images, [name]: image }); src = `voxriva-image:${name}`; }
      if (!src) throw new Error("Upload or choose an image.");
      insert(`<img src="${src}" alt="${escape(alt)}"${width ? ` width="${width}"` : ""} style="max-width:100%;height:auto">`); setOpen(false); setUpload(undefined); setSelected("");
    } catch (error) { setError(error instanceof Error ? error.message : "Image validation failed."); } finally { setBusy(false); }
  }}><Space direction="vertical" style={{ width: "100%" }}><ImageUpload label="Upload image" value={upload as unknown as Value} onChange={(image) => { setUpload(image); setSelected(""); }} /><Select aria-label="Existing image" style={{ width: "100%" }} placeholder="Choose an existing or variable image" value={selected || undefined} onChange={(value) => { setSelected(value); setUpload(undefined); }} options={[...[...Object.keys(images), ...inheritedImages].map((name) => ({ value: `voxriva-image:${name}`, label: `Saved image: ${name}` })), ...variables.map((name) => ({ value: `{{ ${name} }}`, label: `${name}${defaults[name] ? " · runtime default" : " · from payload"}` }))]} /><Input aria-label="Image alternative text" placeholder="Alternative text (empty for decorative images)" value={alt} onChange={(e) => setAlt(e.target.value)} /><InputNumber aria-label="Image width" placeholder="Width in pixels (optional)" min={1} max={4096} value={width} onChange={setWidth} />{error && <Alert type="error" message={error} />}</Space></Modal></>;
}
