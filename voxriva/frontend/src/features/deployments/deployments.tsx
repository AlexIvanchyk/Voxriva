import { QueryContent } from "../../shared/ui/QueryContent";
import { Button, Empty, Input, Select, Space, Table, Tag, Typography } from "antd";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useRecords } from "../../shared/api/client";

interface Version { id: string; branch_name: string; number: number; locale: string }
interface Deployment {
  template_id: string; template_name: string; template_key: string; channel: string;
  scope: string; project_id: string | null; project_name: string | null;
  environment_id: string | null; environment_name: string | null; locale: string;
  version: Version | null; effective_version: Version | null; effective_scope: string | null;
  fallback_used: boolean; updated_at: string | null;
}
const versionLabel = (version: Version) => `${version.branch_name} · v${version.number} · ${version.locale}`;

export function DeploymentsPage() {
  const query = useRecords<Deployment[]>("/deployments");
  const rows = query.data?.data ?? [];
  const [search, setSearch] = useState("");
  const [channel, setChannel] = useState<string>();
  const [project, setProject] = useState<string>();
  const [environment, setEnvironment] = useState<string>();
  const [locale, setLocale] = useState<string>();
  const [status, setStatus] = useState<string>();
  const [scope, setScope] = useState<string>();
  const projects = [...new Map(rows.filter((row) => row.project_id).map((row) => [row.project_id!, { value: row.project_id!, label: row.project_name! }])).values()];
  const options = (values: string[]) => [...new Set(values)].sort().map((value) => ({ value, label: value }));
  const filtered = rows.filter((row) => (!channel || row.channel === channel) && (!project || row.project_id === project)
    && (!environment || row.environment_name === environment) && (!locale || row.locale === locale) && (!scope || row.scope === scope)
    && (!status || (status === "active" ? !!row.effective_version : !row.effective_version))
    && `${row.template_name} ${row.template_key} ${row.project_name ?? ""} ${row.environment_name ?? ""} ${row.effective_version ? versionLabel(row.effective_version) : ""}`.toLowerCase().includes(search.toLowerCase().trim()));
  return <>
    <header className="page-heading"><Typography.Title>Deployments</Typography.Title><p>See where every email and push template is running across your projects and environments.</p></header>
    {query.data && !query.error && <div className="deployment-inventory-summary" aria-label="Deployment summary">
      <div><strong>{new Set(rows.map((row) => row.template_id)).size}</strong><span>Templates</span></div>
      <div><strong>{rows.filter((row) => row.scope === "environment" && row.effective_version).length}</strong><span>Active environment / locale targets</span></div>
      <div><strong>{new Set(rows.filter((row) => row.project_id).map((row) => row.project_id)).size}</strong><span>Connected projects</span></div>
    </div>}
    <section className="deployment-inventory-filters" aria-label="Deployment filters">
      <Input.Search aria-label="Search deployments" placeholder="Search templates, targets or versions" value={search} onChange={(event) => setSearch(event.target.value)} allowClear />
      <Select aria-label="Filter channel" placeholder="All channels" allowClear value={channel} onChange={setChannel} options={[{ value: "email", label: "Email" }, { value: "push", label: "Push" }]} />
      <Select aria-label="Filter project" placeholder="All projects" allowClear value={project} onChange={(value) => { setProject(value); setEnvironment(undefined); }} options={projects} />
      <Select aria-label="Filter environment" placeholder="All environments" allowClear value={environment} onChange={setEnvironment} options={options(rows.filter((row) => !project || row.project_id === project).flatMap((row) => row.environment_name ? [row.environment_name] : []))} />
      <Select aria-label="Filter locale" placeholder="All locales" allowClear value={locale} onChange={setLocale} options={options(rows.map((row) => row.locale))} />
      <Select aria-label="Filter status" placeholder="All statuses" allowClear value={status} onChange={setStatus} options={[{ value: "active", label: "Active" }, { value: "unset", label: "Not configured" }]} />
      <Select aria-label="Filter scope" placeholder="All targets" allowClear value={scope} onChange={setScope} options={[{ value: "environment", label: "Environments" }, { value: "project", label: "Project defaults" }, { value: "global", label: "Global defaults" }]} />
    </section>
    <div className="section-heading"><span className="muted-text">{filtered.length} matching targets · Defaults are shown separately from environment deployments.</span><Space><Button onClick={() => { setSearch(""); setChannel(undefined); setProject(undefined); setEnvironment(undefined); setLocale(undefined); setStatus(undefined); setScope(undefined); }}>Reset filters</Button><Button loading={query.isFetching} onClick={() => void query.refetch()}>Refresh deployments</Button></Space></div>
    
    <QueryContent query={query}><Table<Deployment> className="directory-table" loading={query.isPending} dataSource={filtered}
      rowKey={(row) => `${row.template_id}:${row.scope}:${row.environment_id ?? row.project_id ?? "global"}:${row.locale}`} scroll={{ x: 1050 }}
      pagination={{ pageSize: 20, showSizeChanger: false, hideOnSinglePage: true }}
      locale={{ emptyText: <Empty description={rows.length ? "No deployments match these filters" : "No templates available. Connect a template to a project to start deploying."} /> }} columns={[
        { title: "Template", key: "template", render: (_, row) => <div className="version-identity"><Link to={`/templates/${row.template_id}?tab=deployments&locale=${encodeURIComponent(row.locale)}`}><strong>{row.template_name}</strong></Link><span>{row.template_key}</span></div> },
        { title: "Channel", dataIndex: "channel", render: (value: string) => <Tag color={value === "push" ? "purple" : "blue"}>{value === "push" ? "Push" : "Email"}</Tag> },
        { title: "Project / target", key: "target", render: (_, row) => <div className="version-identity"><strong>{row.project_name ?? "Shared library"}</strong><span>{row.environment_name ?? (row.scope === "global" ? "Global default" : "Project default")}</span></div> },
        { title: "Locale", dataIndex: "locale" },
        { title: "Active version", key: "version", render: (_, row) => row.effective_version ? <div className="version-identity"><strong>{versionLabel(row.effective_version)}</strong><span>{row.version ? "Explicit deployment" : `From ${row.effective_scope}${row.effective_scope === "environment" ? "" : " default"}`}{row.fallback_used ? " · locale fallback" : ""}</span></div> : <Tag>Not configured</Tag> },
        { title: "Deployed", key: "updated", render: (_, row) => row.updated_at ? new Date(row.updated_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—" },
        { title: "", key: "open", render: (_, row) => <Link to={`/templates/${row.template_id}?tab=deployments&locale=${encodeURIComponent(row.locale)}`}>Open matrix</Link> },
      ]} /></QueryContent>
  </>;
}
