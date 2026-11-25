import { Typography } from "antd";
import { Link } from "react-router-dom";
import { useRecords } from "../../shared/api/client";
import { QueryContent } from "../../shared/ui/QueryContent";
import { canEdit, canManage, useProjectContext } from "../projects/projectContext";

export function SetupSteps({ platformAdmin }: { platformAdmin: boolean }) {
  const workspace = useProjectContext();
  if (!platformAdmin && !workspace.projects.some(canEdit)) return null;
  return <SetupInventory platformAdmin={platformAdmin} />;
}

function SetupInventory({ platformAdmin }: { platformAdmin: boolean }) {
  const workspace = useProjectContext();
  const environments = useRecords<{ id: string }[]>("/environments");
  const providers = useRecords<{ id: string }[]>("/providers");
  const templates = useRecords<{ id: string }[]>("/templates");
  const deployments = useRecords<{ scope: string; effective_version: unknown }[]>("/deployments");
  const queries = [environments, providers, templates, deployments];
  const managing = platformAdmin || workspace.projects.some(canManage);
  const editing = platformAdmin || workspace.projects.some(canEdit);
  const deployed = Array.isArray(deployments.data?.data) && deployments.data.data.some((row) => row.scope === "environment" && row.effective_version);
  if (deployed && !queries.some((query) => query.error || query.isPending) && !workspace.error) return null;
  const ready = (data: unknown) => Array.isArray(data) && data.length > 0;
  const steps = [
    { name: platformAdmin ? "Create a project" : "Choose your project", to: "/projects", done: workspace.projects.length > 0, allowed: platformAdmin || workspace.projects.length > 0, description: "Keep an application's delivery settings and team together." },
    { name: "Add an environment", to: "/environments", done: ready(environments.data?.data), allowed: managing, description: "Separate development and production delivery credentials." },
    { name: "Configure and assign a provider", to: "/providers", done: ready(providers.data?.data), allowed: managing, description: "Save delivery settings, test them, and assign a revision to a channel." },
    { name: "Create and publish a template", to: "/templates", done: false, allowed: editing, description: ready(templates.data?.data) ? "Open a template, review test data, and publish a version." : "Connect a template to your project and review its preview." },
    { name: "Deploy a published version", to: "/deployments", done: false, allowed: managing, description: "Choose the environment that should use the version. Publishing alone does not deploy." },
  ];
  return <section className="dashboard-section setup-panel" aria-label="Get started">
    <Typography.Title level={2}>Set up your first delivery</Typography.Title>
    <p>Follow these steps in order. Each screen has its own project filter.</p>
    <QueryContent query={{ isPending: workspace.pending || queries.some((query) => query.isPending), error: workspace.error || queries.find((query) => query.error)?.error, refetch: () => Promise.all([workspace.refresh(), ...queries.map((query) => query.refetch())]) }}>
      <ol>{steps.map((step) => <li key={step.to}><div>{step.allowed ? <Link to={step.to}>{step.name}</Link> : <strong>{step.name}</strong>}{step.done && <span className="muted-text"> · Available</span>}</div><p>{step.description}{!step.allowed && " Ask a project administrator to complete this step."}</p></li>)}</ol>
    </QueryContent>
  </section>;
}
