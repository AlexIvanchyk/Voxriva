import { QueryContent } from "../../shared/ui/QueryContent";
import { FileTextOutlined, PlusOutlined, SearchOutlined } from "@ant-design/icons";
import { Alert, Button, Empty, Form, Input, Radio, Select, Skeleton, Space, Table, Tag, Typography } from "antd";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { errorMessage, useRecords } from "../../shared/api/client";
import { DeleteAction, Editor } from "../../shared/ui/adminForms";
import { canEdit, canManage, useProjectContext } from "../projects/projectContext";
import type { Session } from "../session/session";
import { authenticatedRequest } from "../session/session";
import type { PreviewTarget } from "./layoutPicker";
import { DraftEditor } from "./draftEditor";
import { LanguageSelect, languageLabel } from "./templateFields";
import { TemplateLifecycle } from "./templateLifecycle";

import type { Draft, Template } from "./types";
const { Title } = Typography;
const dialect = "https://json-schema.org/draft/2020-12/schema";
export function initialDraft(): Draft {
  return { contract_version: 1, subject: "", text: "", html: "", title: "", body: "", data: {}, variable_schema: { $schema: dialect, type: "object", properties: {}, additionalProperties: false }, runtime_defaults: {}, preview_context: {}, scenarios: {} };
}

export function TemplatesPage({ session }: { session: Session }) {
  const [params, setParams] = useSearchParams();
  const workspace = useProjectContext();
  const query = useRecords<Template[]>("/templates");
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const filter = params.get("project") ?? undefined;
  const setFilter = (id: string | undefined) => { const next = new URLSearchParams(params); if (id) next.set("project", id); else next.delete("project"); setParams(next); };
  const editable = session.account.platform_admin || workspace.projects.some(canEdit);
  const options = workspace.projects.filter(canEdit).map((item) => ({ value: item.id, label: item.name }));
  const rows = (query.data?.data ?? []).filter((item) => `${item.name} ${item.key}`.toLowerCase().includes(search.toLowerCase())
    && (!filter || item.projects.some((project) => project.id === filter)));
  return <>
    <header className="directory-heading"><div><span className="page-eyebrow">Shared library</span><Title>Templates</Title>
      <p>Create once. Connect the same email or push template to multiple projects.</p></div>
      {editable && <Button type="primary" size="large" icon={<PlusOutlined aria-hidden="true" />} onClick={() => setOpen(true)}>Create template</Button>}</header>
    <div className="directory-toolbar member-filters"><Input aria-label="Search templates" prefix={<SearchOutlined aria-hidden="true" />} placeholder="Search templates" value={search} onChange={(e) => setSearch(e.target.value)} allowClear />
      <Select aria-label="Filter templates by project" placeholder="All connected projects" value={filter} onChange={setFilter} allowClear options={workspace.projects.map((item) => ({ value: item.id, label: item.name }))} /></div>
    
    <QueryContent query={query}><Table<Template> className="directory-table" rowKey="id" loading={query.isPending} dataSource={rows} pagination={rows.length > 20 ? { pageSize: 20 } : false}
      scroll={{ x: 700 }} locale={{ emptyText: <Empty description={search || filter ? "No matching templates" : "No templates yet"} /> }} columns={[
        { title: "Template", key: "name", render: (_, item) => <div className="member-identity"><span className="directory-icon"><FileTextOutlined aria-hidden="true" /></span><div>
          <Link to={`/templates/${item.id}`}><strong>{item.name}</strong></Link><span>{item.key}</span></div></div> },
        { title: "Channel", key: "channel", render: (_, item) => <Tag color={item.channel === "email" ? "blue" : "purple"}>{item.channel === "email" ? item.is_layout ? "Email layout" : "Email" : "Push"}</Tag> },
        { title: "Languages", key: "languages", render: (_, item) => <Space wrap>{item.languages.map((code) => <Tag key={code}>{languageLabel(code)}{code === item.primary_locale ? " · primary" : ""}</Tag>)}</Space> },
        { title: "Connected projects", key: "projects", render: (_, item) => item.project_count ? <Space wrap>{item.projects.map((project) => <Tag key={project.id}>{project.name}</Tag>)}
          {item.project_count > item.projects.length && <Tag>+{item.project_count - item.projects.length} shared</Tag>}</Space> : <span className="muted-text">Not connected</span> },
        { title: "Updated", key: "updated", render: (_, item) => new Date(item.updated_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) },
        { title: "", key: "actions", align: "right", render: (_, item) => <Space><Link to={`/templates/${item.id}`}>{item.editable ? "Open editor" : "Preview"}</Link>
          {item.manage_bindings && !item.has_published_versions && <DeleteAction compact title="Delete" text={`Delete ${item.name} from the shared library and disconnect it from all projects?`} onConfirm={async () => {
            await authenticatedRequest(session, `/templates/${item.id}`, "DELETE"); await query.refetch();
          }} />}</Space> },
      ]} /></QueryContent>
    {open && <Editor<{ name: string; key?: string; channel: "email" | "layout" | "push"; project_ids?: string[]; locale: string }> title="Create template"
      description="Start with an empty draft. Choose the channel and projects that will use it." submitLabel="Create template" close={() => setOpen(false)}
      initial={{ channel: "email", locale: "en", project_ids: canEdit(workspace.project) ? [workspace.project!.id] : [] }} submit={async (values) => {
        const slug = values.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 90);
        const key = values.key || (/^[a-z]/.test(slug) ? slug : `template-${slug || crypto.randomUUID().slice(0, 8)}`);
        const item = await authenticatedRequest<Template>(session, "/templates", "POST", { ...values, key, channel: values.channel === "layout" ? "email" : values.channel, is_layout: values.channel === "layout", project_ids: values.project_ids ?? [], draft: values.channel === "layout" ? { ...initialDraft(), html: "<!-- voxriva:body -->" } : initialDraft() });
        navigate(`/templates/${item.id}`);
      }}>
      <Form.Item name="name" label="Template name" rules={[{ required: true, whitespace: true, max: 100 }]}><Input placeholder="e.g. Account activation" autoFocus /></Form.Item>
      <Form.Item name="channel" label="Channel"><Radio.Group className="channel-options"><Radio.Button value="email"><strong>Email template</strong><small>Subject, HTML, and plain text</small></Radio.Button>
        <Radio.Button value="layout"><strong>Email layout</strong><small>Shared header, footer, and styles</small></Radio.Button>
        <Radio.Button value="push"><strong>Push notification</strong><small>Title, body, and custom data</small></Radio.Button></Radio.Group></Form.Item>
      <Form.Item name="locale" label="Primary language" rules={[{ required: true }]} extra="Start with an empty draft in this language. Add translations later."><LanguageSelect label="Primary language" /></Form.Item>
      <Form.Item name="project_ids" label="Connected projects" extra="The same template can be used by more than one project."
        rules={session.account.platform_admin ? [] : [{ required: true, type: "array", min: 1 }]}><Select mode="multiple" showSearch options={options} placeholder="Select projects" optionFilterProp="label" /></Form.Item>
      <Form.Item name="key" label="Template key" extra="Optional. Generated from the name if left empty." rules={[{ pattern: /^[a-z][a-z0-9_-]{0,99}$/, message: "Start with a lowercase letter; use letters, numbers, hyphens, or underscores." }]}>
        <Input placeholder="account-activation" /></Form.Item>
    </Editor>}
  </>;
}

function TemplateConnections({ item, session, refresh }: { item: Template; session: Session; refresh: () => Promise<unknown> }) {
  const workspace = useProjectContext();
  const [open, setOpen] = useState(false);
  return <div className="template-connections" role="region" aria-label="Connected projects"><div><span className="muted-text">Connected projects</span><Space wrap>
    {item.projects.map((project) => <Tag key={project.id}>{project.name}</Tag>)}{!item.project_count && <span>Not connected yet</span>}
    {item.project_count > item.projects.length && <Tag>Also shared with other projects</Tag>}</Space></div>
    {item.manage_bindings && <Button onClick={() => setOpen(true)}>Manage projects</Button>}
    {open && <Editor<{ project_ids: string[] }> title="Connect template to projects" description="All selected projects will use this shared template. Its draft is kept in one place."
      submitLabel="Save connections" close={() => setOpen(false)} initial={{ project_ids: item.projects.map((project) => project.id) }} submit={async (values) => {
        await authenticatedRequest(session, `/templates/${item.id}/projects`, "PUT", values); await refresh();
      }}><Form.Item name="project_ids" label="Projects" rules={session.account.platform_admin ? [] : [{ required: true, type: "array", min: 1 }]}>
        <Select mode="multiple" showSearch optionFilterProp="label" options={workspace.projects.filter(canManage).map((project) => ({ value: project.id, label: project.name }))} placeholder="Select projects" /></Form.Item></Editor>}
  </div>;
}

export function TemplateEditorPage({ session }: { session: Session }) {
  const { templateId } = useParams();
  const [params, setParams] = useSearchParams();
  const selectedBranch = params.get("branch");
  const path = `/templates/${templateId}`;
  const query = useRecords<Template>(`${path}${selectedBranch ? `?branch_id=${encodeURIComponent(selectedBranch)}` : ""}`);
  const [dirty, setDirty] = useState(false);
  const item = query.data?.data;
  const [selection, setSelection] = useState<{ branch: string; target: PreviewTarget }>();
  const target = item && selection?.branch === item.branch_id ? selection.target : undefined;
  return <div className="template-editor-page"><header className="page-heading"><Link to="/templates">← Back to templates</Link><Title>{item?.name ?? "Template editor"}</Title><p>{item?.key}</p></header>
    {(query.isPending || !query.isFetchedAfterMount) && <Skeleton active />}
    {query.error && <Alert type="error" message={errorMessage(query.error)} />}
    {item && query.isFetchedAfterMount && <><TemplateConnections item={item} session={session} refresh={query.refetch} />
      {!item.editable && <Alert type="info" message="Preview access. Editing a shared template requires editor access in every connected project." />}
      <TemplateLifecycle key={item.id} target={target} item={item} session={session} dirty={dirty} refresh={query.refetch} onBranch={(id) => {
        if (id === item.branch_id) return true;
        if (dirty && !window.confirm("Discard unsaved changes and switch branch?")) return false;
        const next = new URLSearchParams(params); next.set("branch", id); next.delete("locale"); next.delete("tab"); setParams(next); setDirty(false); return true;
      }} renderDraft={(active) => <DraftEditor active={active} onTargetChange={(value) => setSelection({ branch: item.branch_id, target: value })} key={item.branch_id} item={item} session={session} editable={item.editable} path={path} onDirty={setDirty} onSaved={query.refetch} />} /></>}
  </div>;
}
