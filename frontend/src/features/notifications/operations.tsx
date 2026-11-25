import { QueryContent } from "../../shared/ui/QueryContent";
import { Alert, Button, Card, Empty, Select, Space, Statistic, Table, Tabs, Tag, Typography } from "antd";
import { Link, useSearchParams } from "react-router-dom";
import { errorMessage, useRecords } from "../../shared/api/client";
import { useProjectContext } from "../projects/projectContext";

interface Worker { node: string; state: string; last_seen: string }
interface Event { id: string; node: string; event: string; notification_id: string | null; created_at: string }
interface Trend { delivered: number; bounced: number; hour: string; sent: number; failed: number; unknown: number; queued: number; retrying: number; processing: number }
interface Report { counts: Record<string, number>; pending_outbox: number; attempts: number; oldest_waiting_seconds: number; workers: Worker[] | null; broker_depth: number | null; broker_depths: Record<string, number> | null; broker_status: string; events: Event[]; trend: Trend[] }
interface Reference { label: string; href: string | null }
interface Audit { actor?: Reference; target?: Reference; action_label?: string; project_name?: string; id: string; actor_id: string; project_id: string | null; action: string; target_id: string; created_at: string }
interface Environment { id: string; name: string; project_id: string; project_name: string }
const date = (value: string) => new Date(value).toLocaleString();

export function OperationsPage() {
  const { projects } = useProjectContext();
  const [params, setParams] = useSearchParams();
  const project = params.get("project") ?? undefined;
  const environment = params.get("environment") ?? undefined;
  const page = Math.max(1, Number(params.get("page")) || 1);
  const search = new URLSearchParams();
  if (project) search.set("project_id", project);
  if (environment) search.set("environment_id", environment);
  const query = useRecords<Report>(`/operations?${search}`, 3000);
  const audit = useRecords<{ items: Audit[]; total: number }>(`/operations/audit?offset=${(page-1)*25}${project ? `&project_id=${project}` : ""}`, 5000);
  const environments = useRecords<Environment[]>("/environments");
  const report = query.data?.data;
  function filter(key: string, value?: string) { const next = new URLSearchParams(params); if (value) next.set(key, value); else next.delete(key); next.delete("page"); if (key === "project") next.delete("environment"); setParams(next); }
  const names = new Map(projects.map((item) => [item.id, item.name]));
  return <>
    <header className="page-heading"><Typography.Title>Operations</Typography.Title><p>Delivery health, recovery and an audit trail across your projects.</p></header>
    <Tabs activeKey={params.get("tab") ?? "delivery"} onChange={(tab) => { const next = new URLSearchParams(params); next.set("tab", tab); setParams(next); }} items={[
      { key: "delivery", label: "Delivery health", children: <>
        <div className="directory-toolbar member-filters"><Select aria-label="Operations project" placeholder="All projects" allowClear value={project} onChange={(value) => filter("project", value)} options={projects.map((item) => ({ value: item.id, label: item.name }))} />
          <Select aria-label="Operations environment" placeholder="All environments" allowClear value={environment} onChange={(value) => filter("environment", value)} options={(environments.data?.data ?? []).filter((item) => !project || item.project_id === project).map((item) => ({ value: item.id, label: `${item.project_name} / ${item.name}` }))} /><Button onClick={() => void query.refetch()}>Refresh health</Button></div>
        {query.error && <Alert type="error" message={errorMessage(query.error)} />}
        {report && <>
          <div className="operations-stats">{Object.entries(report.counts).map(([state, count]) => <Card key={state}><Statistic title={<Link to={`/notifications?status=${state}${project ? `&project=${project}` : ""}${environment ? `&environment=${environment}` : ""}`}>{state.charAt(0).toUpperCase()+state.slice(1)}</Link>} value={count} /></Card>)}</div>
          <Space wrap className="operations-caption"><Tag>Attempts: {report.attempts}</Tag><Tag>Awaiting publish: {report.pending_outbox}</Tag><Tag>Oldest waiting: {Math.floor(report.oldest_waiting_seconds)}s</Tag>
            {report.workers !== null && <Tag color={report.broker_status === "ready" ? "green" : "red"}>Broker: {report.broker_status} · ready messages (approx.): Email {report.broker_depths?.email ?? "—"} · Push {report.broker_depths?.push ?? "—"}</Tag>}</Space>
          {report.counts.unknown > 0 && <Alert type="warning" showIcon message="Some deliveries have an unknown outcome" description="These messages are never automatically resent. Check provider records before deciding whether to send a new notification." />}
          <Typography.Title level={2}>Last 24 hours</Typography.Title><p className="muted-text">Notifications grouped by creation hour and their current status. Counts come from delivery records.</p>
          <Table<Trend> className="directory-table" rowKey="hour" dataSource={report.trend} pagination={false} scroll={{ x: 700 }} columns={[{ title: "Created hour (UTC)", dataIndex: "hour", render: (hour: string) => hour.replace("T", " ")+":00" }, ...["sent", "delivered", "bounced", "failed", "unknown", "queued", "retrying", "processing"].map((state) => ({ title: state.charAt(0).toUpperCase()+state.slice(1), dataIndex: state }))]} />
          {report.workers !== null && <><Typography.Title level={2}>Workers</Typography.Title><Table<Worker> className="directory-table" rowKey="node" dataSource={report.workers} pagination={false} locale={{ emptyText: <Empty description="Waiting for worker heartbeats. A missing heartbeat does not confirm worker availability." /> }} columns={[{ title: "Worker", dataIndex: "node" }, { title: "State", dataIndex: "state", render: (state: string) => <Tag color={state === "online" ? "green" : "orange"}>{state}</Tag> }, { title: "Last heartbeat", dataIndex: "last_seen", render: date }]} />
          <Typography.Title level={2}>Worker activity</Typography.Title><p className="muted-text">Operational events retained for seven days. Delivery outcomes are recorded in Notifications.</p><Table<Event> className="directory-table" rowKey="id" dataSource={report.events} pagination={{ pageSize: 8, hideOnSinglePage: true, showSizeChanger: false }} scroll={{ x: 700 }} columns={[{ title: "Event", dataIndex: "event" }, { title: "Worker", dataIndex: "node" }, { title: "Notification", key: "notification", render: (_, row) => row.notification_id ? <Link to={`/notifications/${row.notification_id}`}>View delivery</Link> : "—" }, { title: "Time", dataIndex: "created_at", render: date }]} /></>}
        </>}
      </> },
      { key: "audit", label: "Audit log", children: <><div className="directory-toolbar member-filters"><Select aria-label="Audit project" placeholder="All projects" allowClear value={project} onChange={(value) => filter("project", value)} options={projects.map((item) => ({ value: item.id, label: item.name }))} /></div><p className="muted-text">Account, access, configuration and replay actions visible to project administrators.</p><QueryContent query={audit}><Table<Audit> className="directory-table" rowKey="id" dataSource={audit.data?.data.items ?? []} loading={audit.isPending} scroll={{ x: 900 }} pagination={{ current: page, pageSize: 25, total: audit.data?.data.total ?? 0, hideOnSinglePage: true, showSizeChanger: false, onChange: (value) => { const next = new URLSearchParams(params); next.set("page", String(value)); setParams(next); } }} columns={[{ title: "Action", key: "action", render: (_, row) => <div>{row.action_label ?? "Other activity"}<details><summary>Technical details</summary><code>{row.action}</code><div>Actor: {row.actor_id}</div><div>Object: {row.target_id}</div></details></div> }, { title: "Project", key: "project", render: (_, row) => row.project_name ?? (row.project_id ? names.get(row.project_id) ?? "Unavailable project" : "Installation") }, { title: "Actor", key: "actor", render: (_, row) => row.actor?.href ? <Link to={row.actor.href}>{row.actor.label}</Link> : row.actor?.label ?? "Unavailable account" }, { title: "Object", key: "target", render: (_, row) => row.target?.href ? <Link to={row.target.href}>{row.target.label}</Link> : row.target?.label ?? "Unavailable object" }, { title: "Time", dataIndex: "created_at", render: date }]} /></QueryContent></> },
    ]} />
  </>;
}
