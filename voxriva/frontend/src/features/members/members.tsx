import { QueryContent } from "../../shared/ui/QueryContent";
import { PlusOutlined, SearchOutlined, UserAddOutlined, UserOutlined } from "@ant-design/icons";
import { Alert, Avatar, Button, Empty, Form, Input, Select, Space, Table, Tag, Typography } from "antd";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useRecords } from "../../shared/api/client";
import { DeleteAction, Editor } from "../../shared/ui/adminForms";
import { roles } from "../projects/administration";
import type { Project } from "../projects/projectContext";
import { canManage, useProjectContext } from "../projects/projectContext";
import type { Session } from "../session/session";
import { authenticatedRequest } from "../session/session";

type Role = keyof typeof roles;
interface Grant { project_id: string; project_name: string; role: Role; editable: boolean; created_at: string }
interface Member { account_id: string; email: string; display_name: string; inherited: boolean; can_edit_name: boolean; created_at: string; projects: Grant[] }
interface MemberInput { display_name?: string; email: string; password?: string; projects: { project_id?: string; role: Role }[] }
const roleOptions = Object.entries(roles).map(([value, info]) => ({ value, label: info.label, description: info.description }));

export function MembersPage({ session }: { session: Session }) {
  const context = useProjectContext();
  const [params, setParams] = useSearchParams();
  const selected = params.get("project") ?? undefined;
  const filter = <Select aria-label="Filter members by project" placeholder="All projects" allowClear showSearch optionFilterProp="label" value={selected}
    options={context.projects.map((project) => ({ value: project.id, label: project.name }))} onChange={(id) => { const next = new URLSearchParams(params); if (id) next.set("project", id); else next.delete("project"); setParams(next); }} />;
  if (context.pending || context.error) return <QueryContent query={{ isPending: context.pending, error: context.error, refetch: context.refresh }}>{null}</QueryContent>;
  if (context.invalid) return <><Typography.Title>Members</Typography.Title><div className="directory-toolbar">{filter}</div><Alert type="error" message="This project is unavailable. Choose another project using the filter." /></>;
  return <MemberDirectory session={session} projects={context.projects} selected={selected} projectFilter={filter} />;
}

function MemberDirectory({ session, projects, selected, projectFilter }: { session: Session; projects: Project[]; selected?: string; projectFilter: React.ReactNode }) {
  const query = useRecords<Member[]>("/members");
  const [create, setCreate] = useState(false);
  const [edit, setEdit] = useState<Member | null>(null);
  const [search, setSearch] = useState("");
  const [role, setRole] = useState<string>();
  const manageable = projects.filter(canManage);
  const members = query.data?.data ?? [];
  const rows = members.filter((member) => `${member.email} ${member.display_name}`.toLowerCase().includes(search.toLowerCase())
    && (member.inherited ? !role || role === "platform_admin" : member.projects.some((grant) => (!selected || grant.project_id === selected) && (!role || grant.role === role))));
  return <>
    <header className="directory-heading"><div><span className="page-eyebrow">Workspace</span><Typography.Title>Members</Typography.Title><p>One account, with an independent role in each project.</p></div>
      {(session.account.platform_admin || manageable.length > 0) && <Button type="primary" size="large" icon={<UserAddOutlined aria-hidden="true" />} onClick={() => setCreate(true)}>Add member</Button>}</header>
    <div className="directory-summary"><span><strong>{rows.length}</strong> members with access</span><span>{selected ? projects.find((project) => project.id === selected)?.name : "All accessible projects"}</span></div>
    <div className="directory-toolbar member-filters"><Input aria-label="Search members" prefix={<SearchOutlined aria-hidden="true" />} placeholder="Search by name or email" value={search} onChange={(event) => setSearch(event.target.value)} allowClear />
      {projectFilter}<Select aria-label="Filter members by role" placeholder="All roles" value={role} onChange={setRole} allowClear options={[{ value: "platform_admin", label: "Installation admin" }, ...roleOptions]} /></div>
    
    <QueryContent query={query}><Table<Member> className="directory-table" rowKey="account_id" loading={query.isPending} dataSource={rows} pagination={{ pageSize: 20, hideOnSinglePage: true }} scroll={{ x: 800 }}
      locale={{ emptyText: <Empty description={search || role || selected ? "No matching members" : "No members yet"} /> }} columns={[
        { title: "Member", key: "member", render: (_, member) => <div className="member-identity"><Avatar size={42} icon={<UserOutlined aria-hidden="true" />} style={{ background: "#edf0ff", color: "#414ca8" }} />
          <div><strong>{member.display_name || member.email.split("@")[0]} {member.account_id === session.account.id && <Tag>You</Tag>}</strong><span>{member.email}</span></div></div> },
        { title: "Projects and roles", key: "access", render: (_, member) => member.inherited ? <Space><Tag color="gold">Installation admin</Tag><span>Installation-wide · Inherited access</span></Space>
          : <div className="member-project-grants">{member.projects.filter((grant) => !selected || grant.project_id === selected).map((grant) => <div key={grant.project_id} className="member-project-grant">
            <strong>{grant.project_name}</strong><Tag color={roles[grant.role].color}>{roles[grant.role].label}</Tag>
            {grant.editable && <Space size={4}><Button size="small" onClick={() => setEdit(member)}>Change role</Button><DeleteAction compact title="Remove" text={`Remove ${member.display_name || member.email} from ${grant.project_name}? Other project access is preserved.`}
              onConfirm={async () => { await authenticatedRequest(session, `/projects/${grant.project_id}/members/${member.account_id}`, "DELETE"); await query.refetch(); }} /></Space>}
          </div>)}</div> },
        { title: "", key: "edit", render: (_, member) => (member.can_edit_name || !member.inherited && member.account_id !== session.account.id && manageable.length > 0) && <Button onClick={() => setEdit(member)}>Edit member</Button> },
        { title: "Account created", key: "created", render: (_, member) => new Date(member.created_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) },
      ]} /></QueryContent>
    {create && <Editor<MemberInput> title="Add member" description="Create an account and assign access to one or several projects together. Each project has its own role. Existing users keep their profile and password."
      submitLabel="Add member" close={() => setCreate(false)} initial={{ projects: [{ project_id: manageable.some((project) => project.id === selected) ? selected : manageable.length === 1 ? manageable[0].id : undefined, role: "viewer" }] }}
      submit={async (values) => { await authenticatedRequest(session, "/members", "POST", { ...values, password: values.password || undefined }); await query.refetch(); }}>
      <div className="form-grid"><Form.Item name="display_name" label="Full name" rules={[{ max: 100 }]}><Input placeholder="Full name" autoComplete="name" /></Form.Item>
        <Form.Item name="email" label="Email address" rules={[{ required: true, type: "email" }]}><Input placeholder="name@example.com" type="email" autoComplete="off" /></Form.Item></div>
      <Form.Item name="password" label="Initial password" extra="Required for a new user. Leave empty when adding an existing account." rules={[{ min: 12, max: 256, message: "Use at least 12 characters" }]}><Input.Password placeholder="At least 12 characters" autoComplete="new-password" /></Form.Item>
      <ProjectAccessFields projects={manageable} />
      <div className="form-note">Access applies only to the listed projects. All grants are saved together.</div>
    </Editor>}
    {edit && <Editor<{ display_name: string; projects?: { project_id: string; role: Role }[] }> title="Edit member" description="Update the name and project access together. Email cannot be changed. Access in other administrators' projects is preserved."
      submitLabel="Save member" initial={{ display_name: edit.display_name, projects: edit.projects.filter((grant) => manageable.some((project) => project.id === grant.project_id)).map((grant) => ({ project_id: grant.project_id, role: grant.role })) }} close={() => setEdit(null)}
      submit={async (values) => {
        const access = !edit.inherited && edit.account_id !== session.account.id && manageable.length > 0;
        await authenticatedRequest(session, `/members/${edit.account_id}`, "PATCH", { display_name: edit.can_edit_name ? values.display_name : undefined, expected_display_name: edit.display_name,
          ...(access ? { projects: values.projects ?? [], expected_projects: edit.projects.filter((grant) => manageable.some((project) => project.id === grant.project_id)).map((grant) => ({ project_id: grant.project_id, role: grant.role })) } : {}) }); await query.refetch();
      }}>
      <Form.Item label="Email address"><Input aria-label="Email address" value={edit.email} disabled /></Form.Item>
      <Form.Item name="display_name" label="Full name" rules={[{ max: 100 }]}><Input disabled={!edit.can_edit_name} /></Form.Item>
      {!edit.can_edit_name && <p className="form-note">The name is shared across projects. Only its owner or an administrator of all its projects can change it.</p>}
      {!edit.inherited && edit.account_id !== session.account.id && manageable.length > 0 && <ProjectAccessFields projects={manageable} allowEmpty />}
    </Editor>}

  </>;
}

function ProjectAccessFields({ projects, allowEmpty = false }: { projects: Project[]; allowEmpty?: boolean }) {
  const form = Form.useFormInstance();
  const grants: { project_id?: string; role: Role }[] = Form.useWatch("projects", form) ?? [];
  return <Form.List name="projects" rules={[{ validator: async (_, values) => { if (!allowEmpty && !values?.length) throw new Error("Select at least one project"); } }]}>{(fields, { add, remove }, { errors }) => <>
    <div className="section-heading"><Typography.Title level={5}>Project access</Typography.Title><Button size="small" disabled={grants.filter((grant) => grant.project_id).length >= projects.length || grants.length >= 100} onClick={() => {
      const used = new Set(grants.map((grant) => grant.project_id));
      const existing = grants.filter((grant) => grant.project_id);
      form.setFieldValue("projects", [...existing, ...projects.filter((project) => !used.has(project.id)).map((project) => ({ project_id: project.id, role: "viewer" }))].slice(0, 100));
    }}>Add all managed projects</Button></div>
    {fields.map((field, index) => <div className="member-access-row" key={field.key}><div className="form-grid">
      <Form.Item name={[field.name, "project_id"]} label={index ? `Project ${index + 1}` : "Project"} rules={[{ required: true, message: "Select a project" }]}><Select showSearch optionFilterProp="label" placeholder="Choose a project" virtual={false}
        options={projects.map((project) => ({ value: project.id, label: project.name, disabled: grants.some((grant, position) => position !== index && grant.project_id === project.id) }))} /></Form.Item>
      <Form.Item name={[field.name, "role"]} label={index ? `Project role ${index + 1}` : "Project role"} rules={[{ required: true }]}><Select virtual={false} options={roleOptions} optionRender={(option) => <div className="role-option"><strong>{option.data.label}</strong><small>{option.data.description}</small></div>} /></Form.Item>
    </div><Button size="small" danger disabled={!allowEmpty && fields.length === 1} onClick={() => remove(field.name)}>Remove project</Button></div>)}
    <Form.ErrorList errors={errors} /><Button block icon={<PlusOutlined aria-hidden="true" />} disabled={fields.length >= Math.min(projects.length, 100)} onClick={() => add({ role: "viewer" })}>Add another project</Button>
  </>}</Form.List>;
}
