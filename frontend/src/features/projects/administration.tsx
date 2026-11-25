import { QueryContent } from "../../shared/ui/QueryContent";
import { EditOutlined, FolderOutlined, PlusOutlined, SearchOutlined } from "@ant-design/icons";
import { Button, Empty, Input, Space, Tag, Typography } from "antd";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { DeleteAction, Editor, NameField } from "../../shared/ui/adminForms";
import type { Session } from "../session/session";
import { authenticatedRequest } from "../session/session";
import type { Project } from "./projectContext";
import { canManage, useProjectContext } from "./projectContext";

const { Title } = Typography;
export const roles = {
  project_admin: { label: "Project admin", description: "Manage the project, members, environments, and templates.", color: "purple" },
  template_editor: { label: "Template editor", description: "Create and edit templates connected to this project.", color: "blue" },
  operator: { label: "Operator", description: "View project resources and preview saved templates.", color: "cyan" },
  viewer: { label: "Viewer", description: "Read-only access to project resources and the team directory.", color: "default" },
};
export function ProjectsPage({ session }: { session: Session }) {
  const context = useProjectContext();
  const [edit, setEdit] = useState<Project | "new" | null>(null);
  const [search, setSearch] = useState("");
  const filtered = context.projects.filter((item) => item.name.toLowerCase().includes(search.toLowerCase()));
  return <>
    <header className="directory-heading"><div><span className="page-eyebrow">Workspace</span><Title>Projects</Title>
      <p>Keep each application’s environments and team in one place.</p></div>
      {session.account.platform_admin && <Button type="primary" size="large" icon={<PlusOutlined aria-hidden="true" />} onClick={() => setEdit("new")}>Create project</Button>}</header>
    <div className="directory-toolbar"><Input aria-label="Search projects" placeholder="Search projects" prefix={<SearchOutlined aria-hidden="true" />} value={search} onChange={(e) => setSearch(e.target.value)} allowClear /></div>
    
    <QueryContent query={{ isPending: context.pending, error: context.error, refetch: context.refresh }}><div className="project-grid">
      {!filtered.length && <Empty description={search ? "No matching projects" : "No projects yet"} />}
      {filtered.map((item) => <article className="project-card" key={item.id}><div className="project-card-heading"><span className="directory-icon"><FolderOutlined aria-hidden="true" /></span>
        <Tag>{item.role === "platform_admin" ? "Installation admin" : roles[item.role].label}</Tag></div><Title level={2}>{item.name}</Title>
        <p>Manage environments, project access, and connected templates.</p>
        <Space wrap><Link to={`/environments?project=${item.id}`}>Environments</Link><Link to={`/members?project=${item.id}`}>Members</Link>
          <Link to={`/templates?project=${item.id}`}>Templates</Link></Space>
        <div className="project-card-actions">
          {canManage(item) && <Space><Button aria-label={`Rename ${item.name}`} icon={<EditOutlined aria-hidden="true" />} onClick={() => setEdit(item)} />
            <DeleteAction compact title="Delete" text={`Delete ${item.name}, its environments, keys, and project memberships? Library templates remain available.`}
              onConfirm={async () => { await authenticatedRequest(session, `/projects/${item.id}`, "DELETE"); await context.refresh(); }} /></Space>}</div>
      </article>)}
    </div></QueryContent>
    {edit && <Editor<{ name: string }> title={edit === "new" ? "Create project" : "Rename project"}
      description={edit === "new" ? "Give your application a name. You can add environments and team members next." : "Update the name shown throughout this workspace."}
      submitLabel={edit === "new" ? "Create project" : "Save changes"} initial={edit === "new" ? undefined : edit} close={() => setEdit(null)}
      submit={async (values) => { const result = await authenticatedRequest<Project>(session, edit === "new" ? "/projects" : `/projects/${edit.id}`, edit === "new" ? "POST" : "PATCH", values);
        await context.refresh(); if (edit === "new") context.select(result.id); }}><NameField placeholder="e.g. Customer portal" /></Editor>}
  </>;
}

export function ProjectPage() {
  const { projectId } = useParams();
  return <div className="workspace-shortcuts"><Link to={`/environments?project=${projectId}`}>Open environments</Link><Link to={`/members?project=${projectId}`}>Open members</Link></div>;
}

