import { expect, it } from "vitest";
import { deliveryPath, notificationReturnPath } from "./navigation";

it("retains supported filters, search and page through a detail URL", () => {
  const list = "/notifications?status=queued&project=demo&environment=dev&channel=email&recipient_email=taylor%40example.test&page=3";
  const detail = new URL(deliveryPath("delivery", list), "https://voxriva.invalid");
  const returned = new URL(notificationReturnPath(detail.searchParams.get("returnTo")), "https://voxriva.invalid");
  expect(Object.fromEntries(returned.searchParams)).toEqual(Object.fromEntries(new URL(list, "https://voxriva.invalid").searchParams));
});
it.each([null, "https://evil.test", "//evil.test/notifications", "/notifications/../account/security", "/notifications\\@evil.test", "/notifications-other", "/notifications%2f..%2faccount"]) ("rejects unsafe or unrelated return paths: %s", (value) => {
  expect(notificationReturnPath(value)).toBe("/notifications");
});
it("removes unrelated parameters and fragments", () => {
  expect(notificationReturnPath("/notifications?status=failed&redirect=https://evil.test#fragment")).toBe("/notifications?status=failed");
});
