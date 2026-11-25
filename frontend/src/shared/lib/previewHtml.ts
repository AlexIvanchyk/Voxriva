import DOMPurify from "dompurify";

DOMPurify.addHook("uponSanitizeAttribute", (_node, attribute) => {
  if (["src", "poster", "background"].includes(attribute.attrName)
    && !/^data:image\/(png|jpeg|gif|webp);base64,[a-z0-9+/=]+$/i.test(attribute.attrValue)) attribute.keepAttr = false;
  if (attribute.attrName === "style" && /url\s*\(|@import/i.test(attribute.attrValue)) attribute.keepAttr = false;
});


export function isolatedHtml(html: string, images?: unknown) {
  if (Array.isArray(images)) for (const image of images) {
    if (typeof image?.cid === "string" && /^[a-f0-9]{64}@images\.voxriva$/.test(image.cid) && ["image/png", "image/jpeg", "image/webp"].includes(image.media_type) && typeof image.content_base64 === "string" && /^[a-z0-9+/=]+$/i.test(image.content_base64)) html = html.replaceAll(`cid:${image.cid}`, `data:${image.media_type};base64,${image.content_base64}`);
  }
  const clean = DOMPurify.sanitize(html, { WHOLE_DOCUMENT: false, FORBID_TAGS: ["form", "input", "button", "textarea", "select", "iframe", "object", "embed", "base", "meta", "link"], FORBID_ATTR: ["srcset", "action", "formaction", "target", "download", "href", "xlink:href"] });
  return '<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; font-src \'none\'; form-action \'none\'; base-uri \'none\';"><meta name="referrer" content="no-referrer"></head><body>' + clean + "</body></html>";
}

