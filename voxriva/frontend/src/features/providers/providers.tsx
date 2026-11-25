import { QueryContent } from "../../shared/ui/QueryContent";
import { ApiOutlined, MailOutlined, PlusOutlined } from "@ant-design/icons";
import { Alert, Button, Checkbox, Empty, Form, Input, InputNumber, Modal, Select, Space, Switch, Table, Tabs, Tag, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { errorMessage, useRecords } from "../../shared/api/client";
import { Editor, NameField } from "../../shared/ui/adminForms";
import type { Session } from "../session/session";
import { authenticatedRequest } from "../session/session";

interface FieldSchema { title?: string; description?: string; type?: string; enum?: string[]; anyOf?: FieldSchema[]; default?: unknown; minimum?: number; maximum?: number; maxLength?: number; writeOnly?: boolean; format?: string }
interface ProviderType { key: string; name: string; channel: string; capabilities: { test_connection: boolean; test_send: boolean; validate_only: boolean; delivery_confirmation: boolean }; schema: { properties: Record<string, FieldSchema>; required?: string[] } }
interface Revision { id: string; number: number; config: Record<string, unknown>; configured_secrets: string[]; created_at: string }
interface Configuration { id: string; name: string; provider_type: string; channel: string; project_id: string | null; project_name: string | null; editable: boolean; latest: Revision }
interface Project { id: string; name: string; role: string }
interface BindingVersion { configuration_id: string; configuration_name: string; revision_id: string; revision: number; provider_type: string }
interface Binding { scope: string; project_id: string | null; environment_id: string | null; channel: string; label: string; generation: number; direct: BindingVersion | null; effective: BindingVersion | null; effective_scope: string | null; editable: boolean }
interface ConfigValues { name: string; provider_type: string; project_id?: string; config: Record<string, unknown>; clear_secrets?: string[] }
const bindingLabel = (value: BindingVersion) => `${value.configuration_name} · r${value.revision}`;
const date = (value: string) => new Date(value).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export function ProvidersPage({ session }: { session: Session }) {
  const types = useRecords<ProviderType[]>("/providers/types");
  const configurations = useRecords<Configuration[]>("/providers");
  const bindings = useRecords<Binding[]>("/providers/bindings");
  const projects = useRecords<Project[]>("/projects");
  const [editor, setEditor] = useState<Configuration | "new" | null>(null);
  const historyTrigger = useRef<HTMLElement | null>(null);
  const [history, setHistory] = useState<Configuration | null>(null);
  const [sending, setSending] = useState<Configuration | null>(null);
  const [binding, setBinding] = useState<Binding | null>(null);
  const [busy, setBusy] = useState<string>();
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [channel, setChannel] = useState<string>();
  const [bindingSearch, setBindingSearch] = useState("");
  const [bindingProject, setBindingProject] = useState<string>();
  const [bindingChannel, setBindingChannel] = useState<string>();
  const [project, setProject] = useState<string>();
  const rows = configurations.data?.data ?? [];
  const adapters = types.data?.data ?? [];
  const manageable = (projects.data?.data ?? []).filter((value) => ["platform_admin", "project_admin"].includes(value.role));
  const visible = rows.filter((row) => (!channel || row.channel === channel) && (!project || row.project_id === project || project === "shared" && !row.project_id)
    && `${row.name} ${row.provider_type} ${row.project_name ?? "shared"}`.toLowerCase().includes(search.toLowerCase().trim()));
  const bindingRows = (bindings.data?.data ?? []).filter((row) => (!bindingProject || row.project_id === bindingProject || bindingProject === "global" && row.scope === "global")
    && (!bindingChannel || row.channel === bindingChannel) && `${row.label} ${row.effective?.configuration_name ?? ""}`.toLowerCase().includes(bindingSearch.toLowerCase().trim()));
  const refresh = async () => { await Promise.all([configurations.refetch(), bindings.refetch()]); };
  const canValidatePush = adapters.find((value) => value.key === sending?.provider_type)?.capabilities.validate_only ?? false;
  const queryError = types.error ?? projects.error;
  return <>
    <header className="page-heading"><Typography.Title>Providers</Typography.Title><p>Configure delivery services, test saved revisions and assign them to your projects and environments.</p></header>
    <div className="provider-intro"><div className="service-icon icon-indigo"><ApiOutlined aria-hidden="true" /></div><div><strong>Versioned delivery settings</strong><p>Credentials are write-only. Saving creates a new revision; existing bindings stay pinned until you assign another revision.</p></div>
      {(session.account.platform_admin || manageable.length > 0) && <Button type="primary" icon={<PlusOutlined aria-hidden="true" />} disabled={!adapters.length} onClick={() => setEditor("new")}>Add provider</Button>}</div>
    {notice && <Alert type="success" showIcon closable onClose={() => setNotice("")} message={notice} />}
    {(queryError || error) && <Alert type="error" showIcon message={error || errorMessage(queryError)} action={queryError ? <Button onClick={() => void Promise.all([types.refetch(), projects.refetch()])}>Retry provider setup</Button> : undefined} />}
    <Tabs items={[
      { key: "configurations", label: "Configurations", children: <>
        <div className="directory-toolbar"><Input.Search aria-label="Search providers" placeholder="Search providers" value={search} onChange={(event) => setSearch(event.target.value)} allowClear />
          <Select aria-label="Provider channel" placeholder="All channels" allowClear value={channel} onChange={setChannel} options={[{ value: "email", label: "Email" }, { value: "push", label: "Push" }]} />
          <Select aria-label="Provider owner" placeholder="All owners" allowClear value={project} onChange={setProject} options={[{ value: "shared", label: "Shared library" }, ...(projects.data?.data ?? []).map((value) => ({ value: value.id, label: value.name }))]} />
          <Button data-provider-refresh onClick={() => void refresh()}>Refresh providers</Button></div>
        <QueryContent query={configurations}><Table<Configuration> className="directory-table" rowKey="id" dataSource={visible} loading={configurations.isPending} scroll={{ x: 1050 }} pagination={{ pageSize: 15, hideOnSinglePage: true }}
          locale={{ emptyText: <Empty description={rows.length ? "No providers match these filters" : "No providers yet. Add SMTP, Amazon SES or Firebase Cloud Messaging."} /> }} columns={[
            { title: "Provider", key: "name", render: (_, row) => <div className="version-identity"><strong>{row.name}</strong><span>{adapters.find((value) => value.key === row.provider_type)?.name ?? row.provider_type}</span><span>{adapters.find((value) => value.key === row.provider_type)?.capabilities.delivery_confirmation ? "Delivery confirmation via SES events" : "Provider acceptance only"}</span></div> },
            { title: "Channel", dataIndex: "channel", render: (value: string) => <Tag color={value === "email" ? "blue" : "purple"}>{value === "email" ? "Email" : "Push"}</Tag> },
            { title: "Owner", key: "owner", render: (_, row) => row.project_name ?? "Shared library" },
            { title: "Latest revision", key: "revision", render: (_, row) => <div className="version-identity"><strong>r{row.latest.number}</strong><span>{date(row.latest.created_at)}</span></div> },
            { title: "Credentials", key: "secrets", render: (_, row) => <Tag>{row.latest.configured_secrets.length ? `${row.latest.configured_secrets.length} secret configured` : "No credentials"}</Tag> },
            { title: "Actions", key: "actions", render: (_, row) => { const adapter = adapters.find((value) => value.key === row.provider_type); return <Space wrap size={6}>
              {row.editable && <Button onClick={() => setEditor(row)}>Configure</Button>}<Button onClick={(event) => { historyTrigger.current = event.currentTarget; setHistory(row); }}>Revisions</Button>
              {row.editable && adapter?.capabilities.test_connection && <Button loading={busy === row.id} onClick={async () => {
                setBusy(row.id); setError(""); try { const result = await authenticatedRequest<{ message: string }>(session, `/providers/${row.id}/test-connection`, "POST", { revision_id: row.latest.id }); setNotice(`${row.name} · r${row.latest.number}: ${result.message}`); }
                catch (error) { setError(errorMessage(error)); } finally { setBusy(undefined); }
              }}>Test connection</Button>}
              {row.editable && adapter?.capabilities.test_send && row.channel === "push" && <Button onClick={() => setSending(row)}>Test push</Button>}
              {row.editable && adapter?.capabilities.test_send && row.channel === "email" && <Button icon={<MailOutlined aria-hidden="true" />} onClick={() => setSending(row)}>Send test email</Button>}
            </Space>; } },
          ]} /></QueryContent>
      </> },
      { key: "bindings", label: "Channel bindings", children: <>
        <div className="section-heading"><div><Typography.Title level={2}>Delivery routing</Typography.Title><p className="muted-text">Environment → project default → global default. Each assignment pins an exact configuration revision.</p></div><Button onClick={() => void bindings.refetch()}>Refresh bindings</Button></div>
        <div className="directory-toolbar"><Input.Search aria-label="Search provider bindings" placeholder="Search targets or providers" allowClear value={bindingSearch} onChange={(event) => setBindingSearch(event.target.value)} />
          <Select aria-label="Binding project" placeholder="All projects" allowClear value={bindingProject} onChange={setBindingProject} options={[{ value: "global", label: "Global default" }, ...(projects.data?.data ?? []).map((value) => ({ value: value.id, label: value.name }))]} />
          <Select aria-label="Binding channel" placeholder="All channels" allowClear value={bindingChannel} onChange={setBindingChannel} options={[{ value: "email", label: "Email" }, { value: "push", label: "Push" }]} /></div>
        <QueryContent query={bindings}><Table<Binding> className="directory-table" rowKey={(row) => `${row.scope}:${row.environment_id ?? row.project_id ?? "global"}:${row.channel}`} dataSource={bindingRows} loading={bindings.isPending} pagination={{ pageSize: 20, hideOnSinglePage: true }} scroll={{ x: 850 }} columns={[
          { title: "Target", dataIndex: "label" }, { title: "Channel", dataIndex: "channel", render: (value: string) => <Tag>{value === "email" ? "Email" : "Push"}</Tag> },
          { title: "Assigned revision", key: "direct", render: (_, row) => row.direct ? bindingLabel(row.direct) : <span className="muted-text">Not assigned</span> },
          { title: "Active provider", key: "effective", render: (_, row) => row.effective ? <div className="version-identity"><strong>{bindingLabel(row.effective)}</strong><span>From {row.effective_scope}</span></div> : <Tag>Not configured</Tag> },
          { title: "", key: "actions", render: (_, row) => row.editable && <Button disabled={!rows.some((value) => value.channel === row.channel && (!value.project_id || value.project_id === row.project_id))} onClick={() => setBinding(row)}>Assign provider</Button> },
        ]} /></QueryContent>
      </> },
    ]} />
    {editor && <ConfigurationEditor key={editor === "new" ? "new" : editor.id} item={editor === "new" ? null : editor} types={adapters} projects={manageable} platformAdmin={session.account.platform_admin} session={session} close={() => setEditor(null)} done={async () => { await refresh(); setNotice("Provider revision saved. Existing bindings were not changed."); }} />}
    {history && <RevisionHistory item={history} close={() => { setHistory(null); const target = historyTrigger.current; if (target?.isConnected) target.focus(); else document.querySelector<HTMLButtonElement>("[data-provider-refresh]")?.focus(); }} />}
    {sending?.channel === "email" && <Editor<{ recipient: string; subject: string; text: string }> title="Send test email" description={`Send one real email using ${sending.name}, saved revision r${sending.latest.number}. This test does not use templates or create a notification job.`}
      initial={{ subject: "Voxriva email test", text: "This is an explicit test email from Voxriva." }} submitLabel="Send test email" close={() => setSending(null)} submit={async (values) => {
        const result = await authenticatedRequest<{ message: string }>(session, `/providers/${sending.id}/send-test`, "POST", { ...values, revision_id: sending.latest.id }); setNotice(`${sending.name}: ${result.message}`);
      }}><Form.Item name="recipient" label="Recipient email" rules={[{ required: true, type: "email" }]}><Input placeholder="synthetic@example.test" /></Form.Item>
        <Form.Item name="subject" label="Subject" rules={[{ required: true, max: 200 }]}><Input /></Form.Item><Form.Item name="text" label="Message" rules={[{ required: true, max: 10000 }]}><Input.TextArea rows={4} /></Form.Item></Editor>}
    {sending?.channel === "push" && <Editor<{ device_token: string; title: string; body: string; send_real?: boolean }> title="Test push" description={canValidatePush ? `Validate a push using ${sending.name}, saved revision r${sending.latest.number}. Validation does not deliver. Select Send to device only when you want a real push. Provider tests do not create notification history.` : `Send one real push using ${sending.name}, saved revision r${sending.latest.number}. This provider does not support validation without delivery. Provider tests do not create notification history.`}
      initial={{ title: "Voxriva push test", body: "This is an explicit test push from Voxriva.", send_real: !canValidatePush }} submitLabel="Run push test" close={() => setSending(null)} submit={async (values) => {
        const result = await authenticatedRequest<{ message: string }>(session, `/providers/${sending.id}/send-test-push`, "POST", { device_token: values.device_token, title: values.title, body: values.body, validate_only: !values.send_real, revision_id: sending.latest.id }); setNotice(`${sending.name}: ${result.message}`);
      }}><Form.Item name="device_token" label="Device registration token" rules={[{ required: true, min: 16, max: 4096 }]}><Input.Password autoComplete="off" /></Form.Item>
        <Form.Item name="title" label="Title" rules={[{ required: true, max: 200 }]}><Input /></Form.Item><Form.Item name="body" label="Message" rules={[{ required: true, max: 2000 }]}><Input.TextArea rows={4} /></Form.Item>
        <Form.Item name="send_real" valuePropName="checked"><Checkbox disabled={!canValidatePush}>Send to device (deliver a real push)</Checkbox></Form.Item></Editor>}
    {binding && <BindingEditor row={binding} configurations={rows} session={session} close={() => setBinding(null)} done={async () => { await bindings.refetch(); setNotice(`Provider assigned to ${binding.label} · ${binding.channel}.`); }} />}
  </>;
}

function ConfigurationEditor({ item, types, projects, platformAdmin, session, close, done }: { item: Configuration | null; types: ProviderType[]; projects: Project[]; platformAdmin: boolean; session: Session; close: () => void; done: () => Promise<void> }) {
  const [type, setType] = useState(item?.provider_type ?? types[0]?.key);
  const [identity, setIdentity] = useState<{ name: string | undefined; project_id: string | undefined }>({ name: item?.name, project_id: item?.project_id ?? (platformAdmin ? "shared" : projects[0]?.id) });
  const adapter = types.find((value) => value.key === type)!;
  const defaults = Object.fromEntries(Object.entries(adapter.schema.properties).filter(([, field]) => field.default !== undefined && !field.writeOnly).map(([key, field]) => [key, field.default]));
  return <Editor<ConfigValues> key={type} title={item ? `Configure ${item.name}` : "Add provider"} description={item ? `Create revision r${item.latest.number + 1}. Leave secret fields empty to keep stored credentials. Existing assignments retain their pinned revision.` : "Choose an installed provider and save its connection settings. Saving does not contact the provider or send a notification."}
    initial={{ ...identity, provider_type: type, config: { ...defaults, ...item?.latest.config }, clear_secrets: [] }}
    onValuesChange={(_, values) => setIdentity({ name: values.name, project_id: values.project_id })}
    close={close} submitLabel={item ? "Save new revision" : "Create provider"} submit={async (values) => {
      const config = { ...values.config };
      for (const [key, field] of Object.entries(adapter.schema.properties)) if (field.writeOnly && !config[key]) delete config[key];
      if (item) await authenticatedRequest(session, `/providers/${item.id}/revisions`, "POST", { config, expected_revision: item.latest.number, clear_secrets: values.clear_secrets ?? [] });
      else await authenticatedRequest(session, "/providers", "POST", { name: values.name, provider_type: type, project_id: values.project_id === "shared" ? null : values.project_id, config });
      await done();
    }}>
    {!item && <><NameField placeholder="e.g. Local development SMTP" /><div className="form-grid"><Form.Item name="provider_type" label="Provider type" rules={[{ required: true }]}><Select onChange={setType} options={types.map((value) => ({ value: value.key, label: `${value.name} · ${value.channel}` }))} /></Form.Item>
      <Form.Item name="project_id" label="Owner" rules={[{ required: true }]}><Select options={[...(platformAdmin ? [{ value: "shared", label: "Shared library" }] : []), ...projects.map((value) => ({ value: value.id, label: value.name }))]} /></Form.Item></div></>}
    {item?.provider_type === "aws_ses" && <Alert type="info" message="Signed SES delivery events" description={<span>Configure Delivery and Bounce in your SES configuration set, then subscribe SNS to <Typography.Text copyable code>{`${window.location.origin}/api/v1/providers/${item.id}/events/ses`}</Typography.Text>. Use a public HTTPS URL and SNS signature version 2. Saving the topic ARN does not subscribe SNS automatically.</span>} />}
    <div className="provider-schema-fields">{Object.entries(adapter.schema.properties).map(([key, field]) => {
      const schema = field.anyOf?.find((value) => value.type !== "null") ?? field;
      const required = adapter.schema.required?.includes(key) && !(field.writeOnly && item?.latest.configured_secrets.includes(key));
      const label = field.title ?? key;
      return <Form.Item key={key} name={["config", key]} label={label} valuePropName={schema.type === "boolean" ? "checked" : "value"}
        help={field.writeOnly && item?.latest.configured_secrets.includes(key) ? "Stored securely. Leave empty to keep; enter a value to rotate." : field.description}
        rules={[{ required }, ...(schema.maxLength ? [{ max: schema.maxLength }] : [])]}>
        {field.format === "textarea" ? <Input.TextArea rows={7} spellCheck={false} autoComplete="off" placeholder={item ? "Leave empty to keep stored JSON" : "Paste the service account JSON"} /> : field.writeOnly ? <Input.Password autoComplete="new-password" placeholder={item ? "Leave empty to keep" : "Enter secret"} /> : schema.enum ? <Select options={schema.enum.map((value) => ({ value, label: key === "auth_mode" ? ({ default: "Workload credentials", access_keys: "AWS access keys", service_account: "Service account JSON" }[value] ?? value) : value }))} />
          : schema.type === "integer" || schema.type === "number" ? <InputNumber min={schema.minimum} max={schema.maximum} precision={schema.type === "integer" ? 0 : undefined} style={{ width: "100%" }} />
            : schema.type === "boolean" ? <Switch /> : <Input maxLength={schema.maxLength} />}
      </Form.Item>;
    })}</div>
    {!!item?.latest.configured_secrets.length && <Form.Item name="clear_secrets" label="Remove stored secrets"><Checkbox.Group options={item.latest.configured_secrets.map((key) => ({ value: key, label: `Clear ${adapter.schema.properties[key]?.title ?? key}` }))} /></Form.Item>}
  </Editor>;
}

function RevisionHistory({ item, close }: { item: Configuration; close: () => void }) {
  const query = useRecords<Revision[]>(`/providers/${item.id}/revisions`);
  const [open, setOpen] = useState(true);
  return <Modal open={open} afterClose={close} focusTriggerAfterClose={false} title={`Provider revisions · ${item.name}`} width={800} onCancel={() => setOpen(false)} footer={<Button onClick={() => setOpen(false)}>Close revisions</Button>}>
    <p className="muted-text">Immutable saved settings. Secret values are never returned. Bindings and future queued sends pin a specific revision.</p>
    
    <QueryContent query={query}><Table<Revision> rowKey="id" dataSource={query.data?.data ?? []} loading={query.isPending} pagination={false} columns={[
      { title: "Revision", key: "revision", render: (_, row) => <strong>r{row.number}</strong> },
      { title: "Saved", dataIndex: "created_at", render: date },
      { title: "Settings", key: "config", render: (_, row) => <div className="provider-config-summary">{Object.entries(row.config).map(([key, value]) => <span key={key}><strong>{key}:</strong> {String(value)}</span>)}{row.configured_secrets.map((key) => <Tag key={key}>{key}: configured</Tag>)}</div> },
    ]} /></QueryContent>
  </Modal>;
}

function BindingEditor({ row, configurations, session, close, done }: { row: Binding; configurations: Configuration[]; session: Session; close: () => void; done: () => Promise<void> }) {
  const compatible = configurations.filter((value) => value.channel === row.channel && (!value.project_id || value.project_id === row.project_id));
  const [selected, setSelected] = useState(row.direct?.configuration_id ?? compatible[0]?.id);
  const item = compatible.find((value) => value.id === selected);
  return <Editor<{ configuration_id: string; revision_id: string }> title="Assign provider revision" description="Select a saved revision for this channel and target. Concurrent changes require a refresh." close={close} submitLabel="Assign provider"
    initial={{ configuration_id: selected }} submitDisabled={!item} submit={async (values) => {
      await authenticatedRequest(session, "/providers/bindings", "PUT", { scope: row.scope, project_id: row.project_id, environment_id: row.environment_id, channel: row.channel, revision_id: values.revision_id, expected_generation: row.generation }); await done();
    }}><div className="action-target"><strong>{row.label} · {row.channel}</strong><span>Current: {row.effective ? bindingLabel(row.effective) : "Not configured"}</span></div>
    <Form.Item name="configuration_id" label="Provider configuration" rules={[{ required: true }]}><Select onChange={setSelected} options={compatible.map((value) => ({ value: value.id, label: value.name }))} /></Form.Item>
    {item && <RevisionChoice key={item.id} item={item} current={row.direct?.configuration_id === item.id ? row.direct.revision_id : undefined} />}
  </Editor>;
}

function RevisionChoice({ item, current }: { item: Configuration; current?: string }) {
  const query = useRecords<Revision[]>(`/providers/${item.id}/revisions`);
  const form = Form.useFormInstance();
  useEffect(() => { form.setFieldValue("revision_id", current ?? item.latest.id); }, [form, current, item.latest.id]);
  return <><Form.Item name="revision_id" label="Configuration revision" rules={[{ required: true }]}><Select loading={query.isPending} options={(query.data?.data ?? []).map((value) => ({ value: value.id, label: `r${value.number} · ${date(value.created_at)}` }))} /></Form.Item>{query.error && <Alert type="error" message={errorMessage(query.error)} />}</>;
}
