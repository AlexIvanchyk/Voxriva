import { ApiOutlined, ArrowRightOutlined, BarsOutlined, ClockCircleOutlined, CloudServerOutlined, DatabaseOutlined, DeploymentUnitOutlined, KeyOutlined, ThunderboltOutlined } from "@ant-design/icons";
import type { TableColumnsType } from "antd";
import { Alert, Empty, Skeleton, Table, Typography } from "antd";
import { Link } from "react-router-dom";
import type { ContainerStatus, Readiness, SystemInfo, SystemStatus } from "./api";
import { useSystem } from "./api";
import { SetupSteps } from "./SetupSteps";
const { Title } = Typography;

const services = {
  api: { label: "API", icon: ApiOutlined, color: "indigo" },
  postgres: { label: "PostgreSQL", icon: DatabaseOutlined, color: "teal" },
  redis: { label: "Redis", icon: ThunderboltOutlined, color: "rose" },
  migrate: { label: "Migration", icon: DeploymentUnitOutlined, color: "indigo" },
  relay: { label: "Outbox relay", icon: DeploymentUnitOutlined, color: "teal" },
  "email-worker": { label: "Email worker", icon: CloudServerOutlined, color: "indigo" },
  "push-worker": { label: "Push worker", icon: CloudServerOutlined, color: "rose" },
  mailpit: { label: "Local inbox", icon: ApiOutlined, color: "teal" },
  "secrets-init": { label: "Credential key setup", icon: KeyOutlined, color: "indigo" },
  collector: { label: "Collector", icon: CloudServerOutlined, color: "teal" },
};

function serviceDetails(name: string) {
  return services[name as keyof typeof services] ?? { label: name, icon: CloudServerOutlined, color: "indigo" };
}

const badges: Record<string, [label: string, tone: string]> = {
  connected: ["Connected", "positive"],
  ready: ["Ready", "positive"],
  healthy: ["Healthy", "positive"],
  running: ["Running", "positive"],
  completed: ["Completed", "info"],
  missing: ["Missing", "neutral"],
  unconfigured: ["Not configured", "neutral"],
  not_configured: ["No health check", "neutral"],
  unavailable: ["Unavailable", "negative"],
  unhealthy: ["Unhealthy", "negative"],
  exited: ["Exited", "negative"],
  dead: ["Dead", "negative"],
  starting: ["Starting", "warning"],
  restarting: ["Restarting", "warning"],
  paused: ["Paused", "warning"],
  created: ["Created", "neutral"],
  removing: ["Removing", "neutral"],
  unknown: ["Unknown", "neutral"],
};

function StatusTag({ value }: { value: string }) {
  const [label, tone] = badges[value] ?? badges.unknown;
  return <span className={`status-tag tone-${tone}`}><span aria-hidden="true" />{label}</span>;
}

function ServiceIcon({ name }: { name: string }) {
  const { icon: Icon, color } = serviceDetails(name);
  return <span className={`service-icon icon-${color}`} aria-hidden="true"><Icon /></span>;
}

const timeFormatter = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit",
});

function Observation({ value }: { value: string }) {
  return <time dateTime={value} title={value}>{timeFormatter.format(new Date(value))}</time>;
}

const columns: TableColumnsType<ContainerStatus> = [
  {
    title: "Service",
    dataIndex: "service",
    render: (service: string, row) => (
      <div className="table-service">
        <ServiceIcon name={service} />
        <div><strong>{serviceDetails(service).label}</strong><span>{row.name ?? "—"}</span></div>
      </div>
    ),
  },
  { title: "State", dataIndex: "state", render: (state: string) => <StatusTag value={state} /> },
  { title: "Health", dataIndex: "health", render: (health: string) => <StatusTag value={health} /> },
  {
    title: "Restarts",
    dataIndex: "restart_count",
    align: "right",
    render: (count: number | null) => <span className="tabular">{count ?? "—"}</span>,
  },
  { title: "Last observed", dataIndex: "observed_at", render: (value: string) => <Observation value={value} /> },
];

function Dependencies({ report }: { report: Readiness }) {
  return (
    <div className="dependency-grid" aria-label="Dependency readiness">
      {Object.entries(report.checks).map(([name, state]) => (
        <div key={name} className="dependency">
          <ServiceIcon name={name} />
          <div className="dependency-name">{serviceDetails(name).label}</div>
          <StatusTag value={state} />
        </div>
      ))}
    </div>
  );
}

export function Overview({ platformAdmin }: { platformAdmin: boolean }) {
  const info = useSystem<SystemInfo>("info");
  const status = useSystem<Readiness>("readiness");
  const service = info.data?.data;
  return (
    <>
      <header className="page-heading">
        <Title>Overview</Title>
        <p>Check the services that keep Voxriva running.</p>
      </header>
      <SetupSteps platformAdmin={platformAdmin} />
      {info.isError && <Alert showIcon type="error" message="API connection unavailable" />}
      {info.isPending && <Skeleton active paragraph={{ rows: 1 }} />}
      {service && (
        <section className="service-panel" aria-label="Voxriva API">
          <div className="service-panel-icon" aria-hidden="true"><ApiOutlined /></div>
          <div className="service-panel-details">
            <Title level={2}>{service.name} API</Title>
            <p>API version {service.version}</p>
          </div>
          {!info.isError && <StatusTag value="connected" />}
        </section>
      )}
      <section className="dashboard-section" aria-label="Readiness">
        <div className="section-heading">
          <Title level={2}>Readiness</Title>
          {platformAdmin && <Link className="section-link" to="/system/health">View system health <ArrowRightOutlined aria-hidden="true" /></Link>}
        </div>
        {status.isPending && <Skeleton active paragraph={{ rows: 1 }} />}
        {status.isError && <Alert showIcon type="warning" message="Live readiness checks unavailable" />}
        {status.data && !status.isError && <Dependencies report={status.data.data} />}
      </section>
    </>
  );
}

export function SystemHealth() {
  const query = useSystem<SystemStatus>("status");
  const report = query.data?.data;
  const snapshot = report?.monitoring.snapshot;
  const stale = Boolean(snapshot && (query.isError || report?.monitoring.status === "stale"));

  return (
    <>
      <header className="page-heading">
        <Title>System Health</Title>
        <p>Monitor container status and dependency readiness.</p>
      </header>
      {query.isError && <Alert showIcon type="error" message="API connection unavailable" />}
      {query.isPending && <Skeleton active paragraph={{ rows: 4 }} />}
      {report && !query.isError && (
        <section aria-label="Readiness">
          <div className="section-heading"><Title level={2}>Readiness</Title></div>
          <Dependencies report={report.readiness} />
        </section>
      )}
      <section className="dashboard-section" aria-label="Container status">
        <div className="section-heading">
          <div className="section-title">
            <span aria-hidden="true"><BarsOutlined /></span>
            <Title level={2}>Containers</Title>
          </div>
          {snapshot && (
            <div className="snapshot">
              <ClockCircleOutlined aria-hidden="true" /> Last snapshot <Observation value={snapshot.observed_at} />
            </div>
          )}
        </div>
        {stale && (
          <Alert showIcon type="warning" message="Container data is stale"
            description="These are the last container states reported by the collector." />
        )}
        {report?.monitoring.status === "disabled" && (
          <Alert showIcon type="info" message="Container monitoring disabled"
            description="Container monitoring is turned off for this installation. Dependency readiness checks remain active." />
        )}
        {report?.monitoring.status === "unavailable" && (
          <Alert showIcon type="info" message="Container monitoring unavailable"
            description="A collector snapshot has not been received." />
        )}
        {snapshot && (
          <Table
            className="container-table"
            columns={columns}
            dataSource={snapshot.containers}
            rowKey={(row) => `${row.service}/${row.name ?? ""}`}
            pagination={false}
            scroll={{ x: 670 }}
            locale={{ emptyText: <Empty description="No containers were reported" /> }}
          />
        )}
      </section>
    </>
  );
}

