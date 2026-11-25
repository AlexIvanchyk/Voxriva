import { QueryContent } from "../../shared/ui/QueryContent";
import { GlobalOutlined, PlusOutlined } from "@ant-design/icons";
import { Alert, Button, Empty, Form, Input, Select, Space, Table, Typography } from "antd";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useRecords } from "../../shared/api/client";
import { DeleteAction, Editor, NameField } from "../../shared/ui/adminForms";
import type { Session } from "../session/session";
import { authenticatedRequest } from "../session/session";
import { canManage, useProjectContext } from "./projectContext";
interface Environment { id: string; name: string; project_id: string; project_name: string; editable: boolean }

export function EnvironmentsPage({ session }: { session: Session }) {
  const workspace = useProjectContext();
  const [params, setParams] = useSearchParams();
  const selected = params.get("project") ?? undefined;
  const query = useRecords<Environment[]>("/environments");
  const [edit, setEdit] = useState<Environment | "new" | null>(null);
  const [search, setSearch] = useState("");
  const manageable = workspace.projects.filter(canManage);
  const rows = (query.data?.data ?? []).filter((row) => (!selected || row.project_id === selected) && row.name.toLowerCase().includes(search.toLowerCase()));
  return <>
    <header className="directory-heading"><div><span className="page-eyebrow">Workspace</span><Typography.Title>Environments</Typography.Title>
      <p>Browse environments across projects and manage their delivery credentials.</p></div>
      {(session.account.platform_admin || manageable.length > 0) && <Button type="primary" size="large" icon={<PlusOutlined aria-hidden="true" />} onClick={() => setEdit("new")}>Create environment</Button>}</header>
    <div className="directory-toolbar member-filters"><Input aria-label="Search environments" placeholder="Search environments" value={search} onChange={(event) => setSearch(event.target.value)} allowClear />
      <Select aria-label="Filter environments by project" placeholder="All projects" allowClear value={selected} options={workspace.projects.map((project) => ({ value: project.id, label: project.name }))}
        onChange={(id) => { const next = new URLSearchParams(params); if (id) next.set("project", id); else next.delete("project"); setParams(next); }} /></div>
    {workspace.invalid && <Alert type="error" message="This project is unavailable. Choose another project using the filter." />}
    
    <QueryContent query={query}><Table<Environment> className="directory-table" rowKey="id" loading={query.isPending} dataSource={rows} pagination={{ pageSize: 20, hideOnSinglePage: true }}
      locale={{ emptyText: <Empty description={search || selected ? "No matching environments" : "No environments yet"} /> }} columns={[
        { title: "Environment", key: "name", render: (_, row) => <div className="member-identity"><span className="directory-icon"><GlobalOutlined aria-hidden="true" /></span><strong>{row.name}</strong></div> },
        { title: "Project", dataIndex: "project_name" },
        { title: "", key: "actions", align: "right", render: (_, row) => row.editable && <Space><Link to={`/api-keys?project=${row.project_id}&environment=${row.id}`}>API keys</Link>
          <Button onClick={() => setEdit(row)}>Rename</Button><DeleteAction compact title="Delete" text={`Delete ${row.name} and its API keys?`}
            onConfirm={async () => { await authenticatedRequest(session, `/projects/${row.project_id}/environments/${row.id}`, "DELETE"); await query.refetch(); }} /></Space> },
      ]} /></QueryContent>
    {edit && <Editor<{ name: string; project_id?: string }> title={edit === "new" ? "Create environment" : "Rename environment"}
      description={edit === "new" ? "Choose the project that owns this environment." : `This environment belongs to ${edit.project_name}.`} submitLabel={edit === "new" ? "Create environment" : "Save changes"}
      close={() => setEdit(null)} initial={edit === "new" ? { project_id: manageable.some((project) => project.id === selected) ? selected : manageable.length === 1 ? manageable[0].id : undefined } : edit}
      submit={async (values) => { const base = `/projects/${edit === "new" ? values.project_id : edit.project_id}/environments`;
        await authenticatedRequest(session, edit === "new" ? base : `${base}/${edit.id}`, edit === "new" ? "POST" : "PATCH", { name: values.name }); await query.refetch();
      }}>
      {edit === "new" && <Form.Item name="project_id" label="Project" rules={[{ required: true, message: "Select a project" }]}><Select showSearch optionFilterProp="label" options={manageable.map((project) => ({ value: project.id, label: project.name }))} /></Form.Item>}
      <NameField placeholder="e.g. production" /></Editor>}
  </>;
}
