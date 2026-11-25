import { languageLabel } from "./templateFields";
import type { Draft } from "./types";

export interface Version {
  id: string; branch_id: string; branch_name: string; number: number; locale: string; parent_version_id: string | null;
  draft_revision: number; message: string; author: string; created_at: string;
}
export interface Published extends Version { content: Draft }
export interface Branch { id: string; name: string; locale: string; draft_revision: number; source_version_id: string | null; head: Version | null }
export interface Issue { path: string; code: string; message: string }
export interface Difference { before: Published; after: Published; issues: Issue[] }
export interface Scope { scope: "global" | "project" | "environment"; project_id: string | null; environment_id: string | null; locale: string }
export interface Activity { id: string; action: string; generation: number; before: Version | null; after: Version | null; author: string; created_at: string }
export interface Deployment extends Scope {
  label: string; project_name: string | null; environment_name: string | null; generation: number;
  version: Version | null; effective_version: Version | null; effective_scope: string | null; fallback_used: boolean;
  editable: boolean; inherited_version: Version | null; history: Activity[];
}
export interface Matrix { locale: string; fallback_locale: string; rows: Deployment[] }
export const pretty = (value: unknown) => JSON.stringify(value, null, 2);
export const label = (version: Version) => `${languageLabel(version.locale)} · ${version.branch_name} · v${version.number}`;
export const scopeKey = (row: Scope) => row.scope === "global" ? "global" : `${row.scope}:${row.environment_id ?? row.project_id}`;
export const scopeBody = (row: Scope) => ({ scope: row.scope, project_id: row.project_id, environment_id: row.environment_id, locale: row.locale });
export const date = (value: string) => new Date(value).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

