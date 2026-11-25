import type { Draft, Template } from "./types";

// JSON object key order is not part of the draft contract.
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
  return JSON.stringify(value);
}

export interface SaveAttempt { draft: Draft; revision: number; branch: string }
export function saveOutcome(attempt: SaveAttempt, server: Template): "saved" | "conflict" | "unconfirmed" {
  if (server.branch_id !== attempt.branch || server.draft_revision < attempt.revision) return "unconfirmed";
  if (server.draft_revision === attempt.revision) return "unconfirmed";
  return canonical(server.draft) === canonical(attempt.draft) ? "saved" : "conflict";
}
