import { Alert, Space } from "antd";
import { useEffect, useState } from "react";
import { errorMessage } from "../../shared/api/client";
import { authenticatedRequest, type Session } from "../session/session";
import type { LayoutReference } from "./types";
import type { Schema } from "./templateFields";

export interface PreviewTarget { project_id: string; environment_id: string | null }
interface Target extends PreviewTarget { label: string }
interface LayoutOption {
  id: string; name: string; fallback_locale: string;
  versions: { id: string; locale: string; branch: string; number: number }[];
}
interface Options { layouts: LayoutOption[]; targets: Target[] }
export interface SelectedLayout {
  template_id: string; version_id: string; number: number; locale: string; branch: string;
  variable_schema: Schema; runtime_defaults: Schema; images: string[];
}

export function LayoutPicker({ session, path, locale, editable, value, change, target, chooseTarget }: {
  session: Session; path: string; locale: string; editable: boolean; value?: LayoutReference | null;
  change: (ref: LayoutReference | null) => void; target: PreviewTarget | null; chooseTarget: (target: PreviewTarget) => void;
}) {
  const [options, setOptions] = useState<Options>({ layouts: [], targets: [] });
  const [error, setError] = useState("");
  useEffect(() => {
    let current = true;
    authenticatedRequest<Options>(session, path + "/layout-options", "GET").then((data) => {
      if (current && data?.layouts) { setOptions(data); setError(""); }
    }).catch((reason) => { if (current) setError(errorMessage(reason)); });
    return () => { current = false; };
  }, [path, session]);
  const layout = options.layouts.find((item) => item.id === value?.template_id);
  const versions = layout?.versions.filter((version) => [locale, layout.fallback_locale].includes(version.locale)) ?? [];
  const targetIndex = Math.max(0, options.targets.findIndex((item) => item.project_id === target?.project_id && item.environment_id === target?.environment_id));
  return <><Space wrap className="layout-picker">
    <label>Email layout<select aria-label="Email layout" disabled={!editable} value={value?.template_id ?? ""} onChange={(event) => change(event.target.value ? { template_id: event.target.value, version_id: null } : null)}>
      <option value="">No layout</option>
      {options.layouts.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
    </select></label>
    {value && <label>Layout version<select aria-label="Layout version" disabled={!editable} value={value.version_id ?? ""} onChange={(event) => change({ ...value, version_id: event.target.value || null })}>
      <option value="">Active in environment</option>
      {versions.map((version) => <option key={version.id} value={version.id}>{version.locale} · {version.branch} · v{version.number}</option>)}
    </select></label>}
    {value && options.targets.length > 0 && <label>Preview target<select aria-label="Preview target" value={targetIndex} onChange={(event) => chooseTarget(options.targets[Number(event.target.value)])}>
      {options.targets.map((item, index) => <option key={item.environment_id ?? item.project_id} value={index}>{item.label}</option>)}
    </select></label>}
  </Space>{error && <Alert type="error" message={error} />}</>;
}
