import { QueryContent } from "../../shared/ui/QueryContent";
import { Alert, Button, Checkbox, Form, Modal, Select, Skeleton, Space, Table, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { errorMessage, useRecords } from "../../shared/api/client";
import { Editor } from "../../shared/ui/adminForms";
import type { Session } from "../session/session";
import { authenticatedRequest } from "../session/session";
import { languageLabel } from "./templateFields";
import type { Template } from "./types";

import type { Deployment, Difference, Issue, Matrix, Version } from "./lifecycleTypes";
import { date, label, scopeBody, scopeKey } from "./lifecycleTypes";
import { ContractIssues } from "./versionHistory";
export function TemplateDeployments({ item, session, versions, locales, refresh }: { item: Template; session: Session; versions: Version[]; locales: string[]; refresh: () => Promise<unknown> }) {
  const base = `/templates/${item.id}`;
  const [params] = useSearchParams();
  const [locale, setLocale] = useState(params.get("locale") ?? item.locale);
  const query = useRecords<Matrix>(`${base}/deployments?locale=${encodeURIComponent(locale)}`);
  const [action, setAction] = useState<{ row: Deployment; kind: "deploy" | "rollback" } | null>(null);
  const [history, setHistory] = useState<Deployment | null>(null);
  const [fallback, setFallback] = useState(false);
  const [notice, setNotice] = useState("");
  const rows = query.data?.data.rows ?? [];
  const options = versions.filter((version) => version.locale === locale);
  return <>
    <div className="deployment-heading"><div><Typography.Title level={2}>Deployment matrix</Typography.Title><p>Environment → project default → explicit global default. Exact locale first, then the configured fallback.</p></div>
      <Space wrap><Select aria-label="Deployment locale" value={locale} onChange={setLocale} options={locales.map((value) => ({ value, label: languageLabel(value) }))} />
        <Tag>Fallback: {languageLabel(query.data?.data.fallback_locale ?? item.fallback_locale)}</Tag>{item.manage_bindings && <Button onClick={() => setFallback(true)}>Change fallback</Button>}
        <Button onClick={() => void query.refetch()}>Refresh matrix</Button></Space></div>
    {notice && <Alert type="success" message={notice} />}
    <QueryContent query={query}><Table<Deployment> className="directory-table" rowKey={scopeKey} dataSource={rows} loading={query.isPending} pagination={false} scroll={{ x: 1000 }} columns={[
      { title: "Target", key: "target", render: (_, row) => <div className="version-identity"><strong>{row.label}</strong><span>{row.scope === "environment" ? "Environment" : row.scope === "project" ? "Project default" : "Shared library default"} · {row.locale}</span></div> },
      { title: "Explicit version", key: "version", render: (_, row) => row.version ? <Tag color="blue">{label(row.version)}</Tag> : <span className="muted-text">Inherited / unset</span> },
      { title: "Effective version", key: "effective", render: (_, row) => row.effective_version ? <div className="version-identity"><strong>{label(row.effective_version)}</strong><span>Requested {row.locale} → using {row.effective_version.locale} · from {row.effective_scope}{row.fallback_used ? " · fallback applied" : ""}</span></div> : <Tag>Not configured</Tag> },
      { title: "Actions", key: "actions", render: (_, row) => <Space wrap size={6}>
        {row.editable && <><Button disabled={!options.length} onClick={() => setAction({ row, kind: "deploy" })}>Deploy</Button>
          <Button disabled={!row.history.some((event) => [event.before, event.after].some((version) => version && version.id !== row.version?.id))} onClick={() => setAction({ row, kind: "rollback" })}>Roll back</Button>
          </>}
        <Button disabled={!row.history.length} onClick={() => setHistory(row)}>Activity</Button>
      </Space> },
    ]} /></QueryContent>
    <p className="lifecycle-help">Publishing never changes this matrix. Only explicit deployment actions update active pointers.</p>
    {action && <DeploymentAction key={`${scopeKey(action.row)}:${action.kind}`} base={base} action={action.kind} row={action.row} versions={options} session={session} close={() => setAction(null)}
      done={async () => { await Promise.all([query.refetch(), refresh()]); setNotice(`Deployment updated for ${action.row.label} · ${locale}.`); }} />}
    {history && <Modal open title={`Deployment activity · ${history.label} · ${locale}`} width={800} onCancel={() => setHistory(null)} footer={<Button onClick={() => setHistory(null)}>Close activity</Button>}>
      <p className="muted-text">The most recent twenty changes for this target and locale.</p><div className="deployment-activity">{history.history.map((event) => <div key={event.id}>
        <strong>{event.action === "rollback" ? "Roll back" : event.action === "clear" ? "Use inheritance" : event.action === "promote" ? "Promote" : "Deploy"}</strong>
        <p>{event.before ? label(event.before) : "Inherited / unset"} → {event.after ? label(event.after) : "Inherited / unset"}</p><small>{event.author} · {date(event.created_at)}</small></div>)}</div></Modal>}
    {fallback && <Editor<{ locale: string; acknowledge_active_change?: boolean }> title="Change explicit locale fallback"
      description="When no deployment matches a requested locale, resolution tries this locale. Language variants do not fall back implicitly. This can affect active resolutions."
      initial={{ locale: item.fallback_locale }} close={() => setFallback(false)} submitLabel="Save fallback" submit={async (values) => {
        await authenticatedRequest(session, `${base}/fallback`, "PUT", { ...values, expected_locale: item.fallback_locale, acknowledge_active_change: !!values.acknowledge_active_change });
        await Promise.all([refresh(), query.refetch()]);
      }}><Form.Item name="locale" label="Fallback locale" rules={[{ required: true }]}><Select options={[...new Set(versions.map((version) => version.locale))].map((value) => ({ value, label: languageLabel(value) }))} /></Form.Item>
        <Form.Item name="acknowledge_active_change" valuePropName="checked"><Checkbox>I understand this may change the version used by fallback requests.</Checkbox></Form.Item></Editor>}
  </>;
}

function CompatibilityCheck({ base, before, after, loaded }: { base: string; before: string; after: string; loaded: (issues: Issue[]) => void }) {
  const query = useRecords<Difference>(`${base}/versions/diff?before=${before}&after=${after}`);
  useEffect(() => { if (query.data) loaded(query.data.data.issues); }, [query.data, loaded]);
  if (query.isPending) return <Skeleton active paragraph={{ rows: 1 }} />;
  if (query.error) return <Alert type="error" message={errorMessage(query.error)} />;
  return <ContractIssues issues={query.data!.data.issues} />;
}
function DeploymentAction({ base, action, row, versions, session, close, done }: {
  base: string; action: "deploy" | "rollback"; row: Deployment; versions: Version[];
  session: Session; close: () => void; done: () => Promise<void>;
}) {
  const prior = new Map<string, Version>();
  for (const event of row.history) for (const version of [event.before, event.after]) if (version && version.id !== row.version?.id) prior.set(version.id, version);
  const candidates = action === "rollback" ? [...prior.values()] : versions;
  const [chosen, setChosen] = useState(candidates[0]?.id);
  const [ack, setAck] = useState(false);
  const [issues, setIssues] = useState<Issue[] | null>(null);
  const targetVersion = candidates.find((value) => value.id === chosen);
  const compare = row.effective_version && targetVersion && row.effective_version.id !== targetVersion.id;
  const title = action === "rollback" ? "Roll back deployment" : "Deploy published version";
  const button = action === "rollback" ? "Roll back" : "Deploy";
  return <Editor<{ version_id?: string; allow_breaking?: boolean }> title={title}
    description="Review the target and published version. The target is updated atomically; a concurrent change requires a matrix refresh."
    close={close} submitLabel={button} initial={{ version_id: chosen }}
    submitDisabled={!targetVersion || !!compare && (issues === null || issues.length > 0 && !ack)}
    onValuesChange={(changed) => { if (changed.version_id) { setChosen(changed.version_id); setIssues(null); setAck(false); } }}
    submit={async () => {
      const target = { ...scopeBody(row), expected_generation: row.generation, expected_effective_version_id: row.effective_version?.id ?? null, allow_breaking: ack };
      const payload = { ...target, version_id: targetVersion!.id };
      await authenticatedRequest(session, `${base}/deployments/${action}`, "POST", payload); await done();
    }}><div className="action-target"><strong>{row.label}</strong><span>Locale: {row.locale}</span><span>Current effective: {row.effective_version ? label(row.effective_version) : "Not configured"}</span>
      <strong>After this action: {targetVersion ? label(targetVersion) : "Not configured"}</strong></div>
    <Form.Item name="version_id" label={action === "rollback" ? "Previously used version" : "Published version"} rules={[{ required: true }]}><Select options={candidates.map((version) => ({ value: version.id, label: label(version) }))} /></Form.Item>
    {compare && <CompatibilityCheck key={`${row.effective_version!.id}:${targetVersion!.id}`} base={base} before={row.effective_version!.id} after={targetVersion!.id} loaded={setIssues} />}
    {compare && !!issues?.length && <div className="contract-ack"><Checkbox checked={ack} onChange={(event) => setAck(event.target.checked)}>I acknowledge the variable-contract changes shown above.</Checkbox></div>}
  </Editor>;
}
