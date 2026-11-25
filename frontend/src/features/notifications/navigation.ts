const filters = ["project", "environment", "status", "channel", "recipient_email", "page"];
export function notificationReturnPath(value: string | null): string {
  if (!value || !value.startsWith("/notifications")) return "/notifications";
  try {
    const url = new URL(value, "https://voxriva.invalid");
    if (url.origin !== "https://voxriva.invalid" || url.pathname !== "/notifications") return "/notifications";
    const search = new URLSearchParams();
    for (const key of filters) { const value = url.searchParams.get(key); if (value) search.set(key, value); }
    return `/notifications${search.size ? `?${search}` : ""}`;
  } catch { return "/notifications"; }
}
export function deliveryPath(id: string, returnTo: string) {
  return `/notifications/${encodeURIComponent(id)}?${new URLSearchParams({ returnTo: notificationReturnPath(returnTo) })}`;
}
