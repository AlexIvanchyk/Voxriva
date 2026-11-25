import { Alert, Button, Form, Input, InputNumber, Modal, Select, Typography } from "antd";
import { useState } from "react";
import { Editor } from "../../shared/ui/adminForms";
import type { Project } from "./projectContext";
import { canEdit } from "./projectContext";

export interface Named { id: string; name: string }
export interface KeyEnvironment extends Named { project: Named }
export type KeyPurpose = "delivery" | "management";
export interface KeyForm {
  purpose: KeyPurpose; name: string; environment_id: string; expires_in_days: number;
  project_ids: string[]; access: "read" | "write"; management_expires_in_days: number;
}
export const scopeLabel = (scope: KeyEnvironment) => `${scope.project.name} / ${scope.name}`;
export const keyPath = (scope: KeyEnvironment) => `/projects/${scope.project.id}/environments/${scope.id}/keys`;

export function CreateKeyDialog({ environments, projects, currentScope, projectId, close, submit }: {
  environments: KeyEnvironment[]; projects: Project[]; currentScope?: KeyEnvironment; projectId?: string;
  close: () => void; submit: (values: KeyForm) => Promise<void>;
}) {
  return <Editor<KeyForm> title="Create API key" description="Choose what this key can do. Its secret is shown once after creation." submitLabel="Create key" close={close}
    initial={{ purpose: environments.length ? "delivery" : "management", environment_id: currentScope?.id ?? (environments.length === 1 ? environments[0].id : undefined),
      expires_in_days: 90, management_expires_in_days: 30, access: "read", project_ids: projectId && projects.some(p => p.id === projectId) ? [projectId] : [] }} submit={submit}>
    <Form.Item name="purpose" label="Purpose" extra={!environments.length ? "Delivery keys require an environment you administer." : undefined} rules={[{ required: true }]}><Select options={[
      { value: "delivery", label: "Delivery", disabled: !environments.length }, { value: "management", label: "Template / MCP" },
    ]} /></Form.Item>
    <Form.Item noStyle shouldUpdate>{form => {
      const management = form.getFieldValue("purpose") === "management";
      const write = form.getFieldValue("access") === "write";
      const selected: string[] = form.getFieldValue("project_ids") ?? [];
      const eligible = projects.filter(p => !write || canEdit(p));
      const canWriteSelected = selected.every(id => projects.some(p => p.id === id && canEdit(p)));
      return <>
        <Form.Item name="name" label="Name" rules={[{ required: true, whitespace: true, max: management ? 80 : 100 }]}><Input autoFocus maxLength={management ? 80 : 100} placeholder="Enter a name" /></Form.Item>
        {management ? <>
          <Alert type="info" showIcon message="Template authoring only" description="This key belongs to your account. It cannot send notifications, publish or deploy. Your current project roles still apply." />
          <Form.Item name="access" label="Template permissions" extra={!projects.some(canEdit) ? "Your project roles allow read-only credentials." : !canWriteSelected ? "Remove read-only projects before selecting read/write permissions." : undefined} rules={[{ required: true }]}><Select options={[
            { value: "read", label: "Read-only templates" }, { value: "write", label: "Read and write templates", disabled: !projects.some(canEdit) || !canWriteSelected },
          ]} /></Form.Item>
          <Form.Item name="project_ids" label="Allowed projects" rules={[{ required: true, type: "array", min: 1, max: 100, message: "Select 1–100 allowed projects" },
            { validator: async (_, ids: string[] = []) => { if (ids.some(id => !eligible.some(p => p.id === id))) throw new Error("Select projects where you have the chosen permissions"); } }]}>
            <Select mode="multiple" showSearch optionFilterProp="label" placeholder="Choose explicit projects" options={projects.map(p => ({ value: p.id, label: p.name, disabled: write && !canEdit(p) }))} />
          </Form.Item>
          <Button type="link" disabled={!eligible.length || eligible.length > 100} onClick={() => form.setFieldsValue({ project_ids: eligible.map(p => p.id) })}>Select all currently available projects</Button>
          <p className="muted-text">This selects the current projects only. Future projects are not included. Shared-template editing requires permission in every connected project.</p>
          <Form.Item name="management_expires_in_days" label="Expires in days" rules={[{ required: true, type: "number", min: 1, max: 90, message: "Use 1–90 days" }]}><InputNumber min={1} max={90} precision={0} /></Form.Item>
        </> : <>
          <Form.Item name="environment_id" label="Environment" rules={[{ required: true, message: "Select an environment" }]}><Select showSearch optionFilterProp="label" placeholder="Choose an environment" options={environments.map(scope => ({ value: scope.id, label: scopeLabel(scope) }))} /></Form.Item>
          <Form.Item name="expires_in_days" label="Expires in"><Select options={[{ value: 30, label: "30 days" }, { value: 90, label: "90 days" }, { value: 365, label: "365 days" }, { value: 0, label: "No expiration" }]} /></Form.Item>
        </>}
      </>;
    }}</Form.Item>
  </Editor>;
}

export function MCPConnectionInstructions() {
  const [url, setUrl] = useState(`${window.location.origin}/mcp`);
  return <>
    <Alert type="info" showIcon message="Streamable HTTP with a management bearer token" description="Use a client that supports a custom Authorization header. OAuth login and a universal client configuration are not provided." />
    <p>Use the endpoint configured for your installation. The production proxy uses /mcp on the dashboard host; the separate local Compose service defaults to http://127.0.0.1:8001/mcp.</p>
    <label>MCP server URL<Input value={url} onChange={e => setUrl(e.target.value)} /></label>
    <Typography.Paragraph copyable={{ text: url }}>{url}</Typography.Paragraph>
    <p>Set the client header to <Typography.Text code>Authorization: Bearer &lt;management-token&gt;</Typography.Text>, using the secret you saved. Existing secrets cannot be recovered.</p>
    <p>Read drafts and request diffs/previews first. Save changes only after your explicit approval. Keep the token in your client’s secret store.</p>
  </>;
}

export function MCPConnectionDialog({ close }: { close: () => void }) {
  return <Modal open centered styles={{ body: { maxHeight: "calc(100dvh - 220px)", overflowY: "auto" } }} title="MCP connection instructions" onCancel={close} footer={<Button onClick={close}>Done</Button>}><MCPConnectionInstructions /></Modal>;
}
