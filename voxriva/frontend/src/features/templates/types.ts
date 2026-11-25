type Value = null | boolean | number | string | Value[] | { [key: string]: Value };
type Schema = { [key: string]: Value };
export interface Draft {
  contract_version: number; subject: string; text: string; html: string; title: string; body: string;
  images?: Record<string, { media_type: string; content_base64: string }>;
  data: Record<string, string>; variable_schema: Schema; runtime_defaults: Record<string, Value>;
  preview_context: Record<string, Value>; scenarios: Record<string, Record<string, Value>>;
}
export interface Template { id: string; name: string; key: string; channel: "email" | "push"; draft: Draft; draft_revision: number;
  updated_at: string; branch_id: string; branch_name: string; locale: string; fallback_locale: string; has_published_versions: boolean; primary_locale: string; languages: string[]; projects: { id: string; name: string }[]; project_count: number; editable: boolean; manage_bindings: boolean }
