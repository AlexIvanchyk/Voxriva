import { KeyOutlined, PlusOutlined, SearchOutlined } from "@ant-design/icons";
import type { TableColumnsType } from "antd";
import { Alert, Button, Empty, Input, Modal, Select, Skeleton, Space, Table, Typography, message } from "antd";
import { useState } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";
import { errorMessage, useRecords } from "../../shared/api/client";
import { DeleteAction } from "../../shared/ui/adminForms";
import type { Session } from "../session/session";
import { authenticatedRequest } from "../session/session";
import { IntegrationExamples } from "./integrationExamples";
import { CreateKeyDialog, keyPath, MCPConnectionDialog, MCPConnectionInstructions, scopeLabel } from "./keyDialogs";
import type { KeyEnvironment, KeyForm, KeyPurpose } from "./keyDialogs";
import { canManage, useProjectContext } from "./projectContext";

interface KeyBase { id: string; name: string; expires_at: string | null; revoked_at: string | null }
interface DeliveryKey extends KeyBase { environment_id: string; prefix: string }
interface ManagementKey extends KeyBase { project_ids: string[]; scopes: string[]; created_at: string }
interface KeyInventory { environments: KeyEnvironment[]; keys: DeliveryKey[] }
type KeyRow = (DeliveryKey & { purpose: "delivery"; environment: KeyEnvironment }) | (ManagementKey & { purpose: "management" });
type Issued = { secret: string; purpose: "delivery"; scope: KeyEnvironment } | { secret: string; purpose: "management"; credential: ManagementKey };
const statusOptions = ["All statuses", "Active", "Expired", "Revoked"] as const;
const dateFormat = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });
function keyStatus(key: KeyBase) {
  return key.revoked_at ? "Revoked" : key.expires_at && Date.parse(key.expires_at) <= Date.now() ? "Expired" : "Active";
}
export function LegacyKeysPage() {
  const { environmentId = "", projectId } = useParams();
  return <Navigate replace to={`/api-keys?environment=${encodeURIComponent(environmentId)}${projectId ? `&project=${encodeURIComponent(projectId)}` : ""}`} />;
}

export function ApiKeysPage({ session }: { session: Session }) {
  const delivery = useRecords<KeyInventory>("/api-keys");
  const management = useRecords<ManagementKey[]>("/management-credentials");
  const workspace = useProjectContext();
  const { projects } = workspace;
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<typeof statusOptions[number]>("All statuses");
  const [purpose, setPurpose] = useState<KeyPurpose | undefined>();
  const [create, setCreate] = useState(false);
  const [integration, setIntegration] = useState<KeyEnvironment | null>(null);
  const [mcpConnection, setMcpConnection] = useState(false);
  const [issued, setIssued] = useState<Issued | null>(null);
  const [showInstructions, setShowInstructions] = useState(false);
  const [feedback, holder] = message.useMessage();
  const projectId = params.get("project") ?? undefined;
  const inventory = delivery.data?.data;
  const environments = (inventory?.environments ?? []).filter(scope => !projectId || scope.project.id === projectId);
  const scopes = new Map(environments.map(scope => [scope.id, scope]));
  const scopeId = params.get("environment");
  const currentScope = scopeId ? scopes.get(scopeId) : undefined;
  const searchTerm = search.trim().toLowerCase();
  const projectName = (id: string) => projects.find(p => p.id === id)?.name ?? `Unavailable project (${id})`;
  const deliveryRows: KeyRow[] = (inventory?.keys ?? []).flatMap(key => {
    const environment = scopes.get(key.environment_id);
    return environment && (!scopeId || scopeId === environment.id) ? [{ ...key, purpose: "delivery" as const, environment }] : [];
  });
  const managementRows: KeyRow[] = (management.data?.data ?? []).filter(key => !projectId || key.project_ids.includes(projectId)).map(key => ({ ...key, purpose: "management" }));
  const rows = [...deliveryRows, ...managementRows].filter(key => (!purpose || key.purpose === purpose) && (!scopeId || key.purpose === "delivery") &&
    (status === "All statuses" || keyStatus(key) === status) &&
    `${key.name} ${key.purpose === "delivery" ? `${key.prefix} ${scopeLabel(key.environment)} Delivery` : `Template MCP ${key.project_ids.map(projectName).join(" ")} ${key.scopes.join(" ")}`}`.toLowerCase().includes(searchTerm));
  const loading = delivery.isPending || management.isPending || workspace.pending;
  const canCreate = !workspace.pending && !workspace.error && (projects.length > 0 || environments.length > 0);
  const columns: TableColumnsType<KeyRow> = [
    { title: "Name", key: "name", width: 220, render: (_, key) => <div className="keys-identity"><span className="keys-row-icon" aria-hidden="true"><KeyOutlined /></span><div><strong>{key.name}</strong><code title={key.purpose === "management" ? key.id : undefined}>{key.purpose === "delivery" ? key.prefix : key.id.slice(0, 8)}…</code></div></div> },
    { title: "Purpose", key: "purpose", width: 135, render: (_, key) => key.purpose === "delivery" ? "Delivery" : "Template / MCP" },
    { title: "Scope", key: "scope", width: 250, render: (_, key) => key.purpose === "delivery" ? <div className="keys-scope"><strong>{key.environment.name}</strong><span>{key.environment.project.name}</span></div> : <div className="keys-scope"><strong>{key.project_ids.map(projectName).join(", ")}</strong><span>Your account · {key.project_ids.length} project(s)</span></div> },
    { title: "Permissions", key: "permissions", width: 160, render: (_, key) => key.purpose === "delivery" ? "Environment delivery" : key.scopes.includes("templates:write") ? "Read / write templates" : "Read-only templates" },
    { title: "Status", key: "status", width: 100, render: (_, key) => { const value = keyStatus(key); return <span className={`key-state key-state-${value.toLowerCase()}`}><span aria-hidden="true" />{value}</span>; } },
    { title: "Expires", key: "expires", width: 115, render: (_, key) => key.expires_at ? <time dateTime={key.expires_at}>{dateFormat.format(new Date(key.expires_at))}</time> : <span className="keys-muted">Never</span> },
    { title: "Integration", key: "integration", width: 110, render: (_, key) => <Button disabled={keyStatus(key) !== "Active"} onClick={() => key.purpose === "delivery" ? setIntegration(key.environment) : setMcpConnection(true)}>{key.purpose === "delivery" ? "Examples" : "Connect"}</Button> },
    { title: "Actions", key: "actions", width: 88, align: "right", render: (_, key) => !key.revoked_at && <DeleteAction compact title="Revoke" text={`Revoke ${key.name}? Subsequent requests will be rejected; an operation already in progress may finish.`} onConfirm={async () => {
      await authenticatedRequest(session, key.purpose === "delivery" ? `${keyPath(key.environment)}/${key.id}` : `/management-credentials/${key.id}`, "DELETE");
      void feedback.success("Key revoked");
      await (key.purpose === "delivery" ? delivery.refetch() : management.refetch());
    }} /> },
  ];
  return <div className="keys-page">{holder}
    <header className="keys-heading"><div className="keys-title"><span className="keys-title-icon" aria-hidden="true"><KeyOutlined /></span><div><Typography.Title>API keys</Typography.Title><p>Manage delivery keys and your template authoring credentials.</p></div></div>
      {canCreate && <Button type="primary" size="large" icon={<PlusOutlined aria-hidden="true" />} onClick={() => setCreate(true)}>Create API key</Button>}
    </header>
    <div className="directory-toolbar member-filters"><Select aria-label="Filter keys by project" placeholder="All projects" allowClear value={projectId} options={projects.map(p => ({ value: p.id, label: p.name }))} onChange={id => { const next = new URLSearchParams(params); if (id) next.set("project", id); else next.delete("project"); next.delete("environment"); setParams(next); }} /></div>
    {!!workspace.error && <Alert type="error" message={errorMessage(workspace.error)} action={<Button onClick={() => void workspace.refresh()}>Retry projects</Button>} />}
    {projectId && !workspace.pending && !projects.some(p => p.id === projectId) && <Alert type="warning" message="This project is unavailable. Choose another project using the filter." />}
    {loading && <Skeleton active paragraph={{ rows: 4 }} />}
    {delivery.isError && <Alert showIcon type="error" message={`Delivery keys: ${errorMessage(delivery.error)}`} action={<Button size="small" onClick={() => void delivery.refetch()}>Retry delivery keys</Button>} />}
    {management.isError && <Alert showIcon type="error" message={`Template / MCP keys: ${errorMessage(management.error)}`} action={<Button size="small" onClick={() => void management.refetch()}>Retry MCP keys</Button>} />}
    {!loading && <section className="keys-panel" aria-label="API key inventory">
      <div className="keys-toolbar"><Input className="keys-search" aria-label="Search keys" placeholder="Search keys" prefix={<SearchOutlined aria-hidden="true" />} value={search} onChange={e => setSearch(e.target.value)} allowClear />
        <Select aria-label="Filter keys by purpose" placeholder="All purposes" allowClear value={purpose} options={[{ value: "delivery", label: "Delivery" }, { value: "management", label: "Template / MCP" }]} onChange={setPurpose} />
        {(environments.length > 0 || scopeId) && <Select className="keys-environment-filter" aria-label="Filter by environment" placeholder="All environments" showSearch optionFilterProp="label" allowClear value={currentScope?.id} options={environments.map(scope => ({ value: scope.id, label: scopeLabel(scope) }))} onChange={value => { const next = new URLSearchParams(params); if (value) next.set("environment", value); else next.delete("environment"); setParams(next); }} />}
        <Select className="keys-status-filter" aria-label="Filter by status" value={status} options={statusOptions.map(value => ({ value, label: value }))} onChange={setStatus} />
      </div>
      <p className="muted-text" style={{ margin: "12px 14px" }}>MCP scopes remain subject to your current project roles.</p>
      {scopeId && <Alert type={currentScope ? "info" : "warning"} showIcon message={currentScope ? "Showing delivery keys for this environment. Clear the environment filter to include MCP keys." : "This environment is unavailable"} action={<Button size="small" onClick={() => { const next = new URLSearchParams(params); next.delete("environment"); setParams(next); }}>Show all environments</Button>} />}
      <Table<KeyRow> className="keys-table" rowKey={key => `${key.purpose}-${key.id}`} columns={columns} dataSource={rows} scroll={{ x: 1120 }} pagination={rows.length > 25 ? { pageSize: 25, showSizeChanger: false } : false}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={delivery.isError || management.isError ? "Some keys could not be loaded. Retry the failed request above." : searchTerm || purpose || scopeId || status !== "All statuses" ? "No matching keys" : "No API keys yet"}>{!projects.length && <Link to="/projects">Open projects</Link>}</Empty> }} />
      {!environments.length && (session.account.platform_admin || projects.some(canManage)) && <p className="muted-text">Delivery keys need an environment. <Link to="/environments">Open environments</Link>. Template / MCP keys use explicit projects.</p>}
    </section>}
    {create && <CreateKeyDialog environments={environments} projects={projects} currentScope={currentScope} projectId={projectId} close={() => setCreate(false)} submit={async (values: KeyForm) => {
      if (values.purpose === "management") {
        const result = await authenticatedRequest<{ credential: ManagementKey; token: string }>(session, "/management-credentials", "POST", { name: values.name, project_ids: values.project_ids, scopes: values.access === "write" ? ["templates:read", "templates:write"] : ["templates:read"], expires_in_days: values.management_expires_in_days });
        setIssued({ purpose: "management", secret: result.token, credential: result.credential });
        const next = new URLSearchParams(params); next.delete("environment"); setParams(next);
        void management.refetch();
      } else {
        const scope = scopes.get(values.environment_id);
        if (!scope) throw new Error("Environment unavailable");
        const result = await authenticatedRequest<{ key: string }>(session, keyPath(scope), "POST", { name: values.name, expires_in_days: values.expires_in_days || null });
        setIssued({ purpose: "delivery", secret: result.key, scope });
        if (scopeId && scopeId !== scope.id) setParams({ project: scope.project.id, environment: scope.id });
        void delivery.refetch();
      }
      setShowInstructions(false); setSearch(""); setStatus("All statuses"); setPurpose(undefined);
    }} />}
    {integration && <IntegrationExamples key={integration.id} scope={integration} pendingSecret={!!issued} close={() => setIntegration(null)} />}
    {mcpConnection && <MCPConnectionDialog close={() => setMcpConnection(false)} />}
    {!create && issued && !integration && <Modal open centered styles={{ body: { maxHeight: "calc(100dvh - 220px)", overflowY: "auto" } }} title="Copy your API key" closable={false} maskClosable={false} keyboard={false}
      footer={<Space>{issued.purpose === "delivery" ? <Button onClick={() => setIntegration(issued.scope)}>Integration examples</Button> : <Button onClick={() => setShowInstructions(value => !value)}>Connection instructions</Button>}<Button type="primary" onClick={() => { setIssued(null); setShowInstructions(false); }}>Done</Button></Space>}>
      <p className="keys-muted">{issued.purpose === "delivery" ? scopeLabel(issued.scope) : `Template / MCP · ${issued.credential.project_ids.map(projectName).join(", ")}`}</p>
      <p>Save this key now. It’s shown only once. Choose Done when you have saved it.</p>
      <Typography.Paragraph copyable className="issued-key">{issued.secret}</Typography.Paragraph>
      {issued.purpose === "management" && showInstructions && <MCPConnectionInstructions />}
    </Modal>}
  </div>;
}
