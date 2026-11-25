import { DiffOutlined } from "@ant-design/icons";
import { DiffEditor } from "@monaco-editor/react";
import { Alert, Select, Skeleton, Space, Tabs, Tag, Typography } from "antd";
import { useState } from "react";
import { errorMessage, useRecords } from "../../shared/api/client";
import { contentChanges } from "./templateFields";
import type { Draft } from "./types";

import type { Difference, Issue, Version } from "./lifecycleTypes";
import { label, pretty } from "./lifecycleTypes";
export function VersionDiff({ base, versions }: { base: string; versions: Version[] }) {
  const [before, setBefore] = useState<string>();
  const [after, setAfter] = useState<string>();
  if (versions.length < 2) return null;
  const a = before ?? versions[1].id, b = after ?? versions[0].id;
  return <section className="version-diff"><div className="section-heading"><Typography.Title level={2}><DiffOutlined aria-hidden="true" /> Compare versions</Typography.Title></div>
    <div className="comparison-selectors"><label>Original<Select aria-label="Original version" value={a} onChange={setBefore} options={versions.map((row) => ({ value: row.id, label: label(row) }))} /></label>
      <label>Updated<Select aria-label="Updated version" value={b} onChange={setAfter} options={versions.map((row) => ({ value: row.id, label: label(row) }))} /></label></div>
    <DiffView key={`${a}:${b}`} base={base} before={a} after={b} />
  </section>;
}
function DiffView({ base, before, after }: { base: string; before: string; after: string }) {
  const query = useRecords<Difference>(`${base}/versions/diff?before=${before}&after=${after}`);
  if (query.isPending) return <Skeleton active />;
  if (query.error) return <Alert type="error" message={errorMessage(query.error)} />;
  const data = query.data!.data;
  const source = (content: Draft) => { const { variable_schema, preview_context, scenarios, ...fields } = content; void variable_schema; void preview_context; void scenarios; return fields; };
  return <><Typography.Title level={4}>Changed sections</Typography.Title><Space wrap>{contentChanges(data.before.content, data.after.content).map((value) => <Tag key={value}>{value}</Tag>)}</Space><ContractIssues issues={data.issues} /><Tabs items={[
    { key: "content", label: "Content and runtime defaults", children: <DiffEditor height={380} language="json" original={pretty(source(data.before.content))} modified={pretty(source(data.after.content))}
      options={{ readOnly: true, renderSideBySide: true, minimap: { enabled: false }, automaticLayout: true, originalAriaLabel: "Original published content", modifiedAriaLabel: "Updated published content" }} /> },
    { key: "schema", label: "Variable schema", children: <DiffEditor height={380} language="json" original={pretty(data.before.content.variable_schema)} modified={pretty(data.after.content.variable_schema)} options={{ readOnly: true, minimap: { enabled: false }, automaticLayout: true }} /> },
  ]} /></>;
}
export function ContractIssues({ issues }: { issues: Issue[] }) {
  return issues.length ? <Alert type="warning" showIcon message="Variable-contract changes need review" description={<ul>{issues.map((issue, index) => <li key={index}><strong>{issue.path}</strong>: {issue.message}</li>)}</ul>} />
    : <Alert type="success" message="No incompatible variable-contract changes detected" />;
}

