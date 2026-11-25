import { deliveryPath, notificationReturnPath } from "./navigation";
import { QueryContent } from "../../shared/ui/QueryContent";
import { Alert, Button, Checkbox, Empty, Form, Input, Modal, Select, Skeleton, Space, Table, Tag, Typography } from "antd";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { errorMessage, useRecords } from "../../shared/api/client";
import { useProjectContext } from "../projects/projectContext";
import type { Session } from "../session/session";
import { authenticatedRequest } from "../session/session";

interface Resolution { project_name: string; environment_name: string; template_name: string; template_key: string; branch_name: string; template_version: number; resolved_locale: string; fallback_used: boolean; provider_name: string; provider_revision: number; provider_type: string; provider_scope: string }
interface Notification { id: string; project_id: string; environment_id: string; template_version_id: string; provider_revision_id: string; channel: string; locale: string; recipient_mask: string; recipient_email?: string | null; status: string; resolution: Resolution; error_code: string | null; error_message: string | null; created_at: string; updated_at: string }
interface Attempt { number: number; status: string; error_message: string | null; retryable: boolean; provider_message_id: string | null; started_at: string; finished_at: string | null }
interface ProviderEvent { id: string; event: string; occurred_at: string; received_at: string }
interface Detail extends Notification { provider_events: ProviderEvent[]; attempts: Attempt[]; next_attempt_at: string | null; replay_of_id: string | null; payload_available: boolean; replay_allowed: boolean; expires_at: string | null }
interface Inventory { items: Notification[]; total: number; limit: number; offset: number }
interface Environment { id: string; name: string; project_id: string; project_name: string }
const states = ["queued", "retrying", "processing", "sent", "delivered", "bounced", "failed", "unknown"];
const date = (value: string) => new Date(value).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
const title = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);
function State({ value }: { value: string }) { return <Tag color={{ queued: "geekblue", retrying: "purple", processing: "blue", sent: "green", delivered: "green", bounced: "red", failed: "red", unknown: "orange" }[value]}>{title(value)}</Tag>; }

export function NotificationsPage({ session }: { session: Session }) {
  const { notificationId } = useParams();
  return notificationId ? <NotificationDetails identifier={notificationId} session={session} /> : <NotificationHistory />;
}

function NotificationHistory() {
  const { projects } = useProjectContext();
  const environments = useRecords<Environment[]>("/environments");
  const [params, setParams] = useSearchParams();
  const project = params.get("project") ?? undefined;
  const environment = params.get("environment") ?? undefined;
  const status = params.get("status") ?? undefined;
  const channel = params.get("channel") ?? undefined;
  const recipientEmail = params.get("recipient_email") ?? "";
  const page = Math.max(1, Number(params.get("page")) || 1);
  const search = new URLSearchParams({ limit: "25", offset: String((page - 1) * 25) });
  if (project) search.set("project_id", project);
  if (environment) search.set("environment_id", environment);
  if (status) search.set("status", status);
  if (channel) search.set("channel", channel);
  if (recipientEmail) search.set("recipient_email", recipientEmail);
  const returnTo = notificationReturnPath(`/notifications?${params}`);
  const query = useRecords<Inventory>(`/notifications?${search}`, 2000);
  function filter(key: string, value?: string) { const next = new URLSearchParams(params); if (value) next.set(key, value); else next.delete(key); next.delete("page"); if (key === "project") next.delete("environment"); setParams(next); }
  return <>
    <header className="page-heading"><Typography.Title>Notifications</Typography.Title><p>Follow delivery across projects and inspect the exact template and provider revision used.</p></header>
    <div className="directory-toolbar member-filters notification-filters">
      <Select aria-label="Notification project" placeholder="All projects" allowClear value={project} onChange={(value) => filter("project", value)} options={projects.map((item) => ({ value: item.id, label: item.name }))} />
      <Select aria-label="Notification environment" placeholder="All environments" allowClear value={environment} onChange={(value) => filter("environment", value)} options={(environments.data?.data ?? []).filter((item) => !project || item.project_id === project).map((item) => ({ value: item.id, label: `${item.project_name} / ${item.name}` }))} />
      <Select aria-label="Notification status" placeholder="All statuses" allowClear value={status} onChange={(value) => filter("status", value)} options={states.map((value) => ({ value, label: title(value) }))} />
      <Select aria-label="Notification channel" placeholder="All channels" allowClear value={channel} onChange={(value) => filter("channel", value)} options={[{ value: "email", label: "Email" }, { value: "push", label: "Push" }]} />
      <Input.Search key={recipientEmail} aria-label="Search recipient email" placeholder="Search recipient email" defaultValue={recipientEmail} allowClear onSearch={(value) => filter("recipient_email", value.trim())} style={{ width: 280 }} />
      <Button onClick={() => void query.refetch()}>Refresh notifications</Button>
    </div>
    <p className="muted-text">Updates automatically. Sent means the provider accepted the message, rather than confirmed inbox delivery.</p>
    
    <QueryContent query={query}><Table<Notification> className="directory-table" rowKey="id" loading={query.isPending} dataSource={query.data?.data.items ?? []} scroll={{ x: 1000 }}
      pagination={{ current: page, pageSize: 25, total: query.data?.data.total ?? 0, showSizeChanger: false, hideOnSinglePage: true, onChange: (value) => { const next = new URLSearchParams(params); next.set("page", String(value)); setParams(next); } }}
      locale={{ emptyText: <Empty description="No notifications match these filters. Submit a notification using an environment API key to begin." /> }} columns={[
        { title: "Notification", key: "template", render: (_, row) => <div className="version-identity"><Link to={deliveryPath(row.id, returnTo)}><strong>{row.resolution.template_name}</strong></Link><span>{row.resolution.template_key} · {row.channel}</span></div> },
        { title: "Project / environment", key: "scope", render: (_, row) => <div className="version-identity"><strong>{row.resolution.project_name}</strong><span>{row.resolution.environment_name}</span></div> },
        { title: "Recipient", key: "recipient", render: (_, row) => row.recipient_email ?? row.recipient_mask },
        { title: "Status", key: "status", render: (_, row) => <State value={row.status} /> },
        { title: "Template / provider", key: "pins", render: (_, row) => <div className="version-identity"><strong>{row.resolution.branch_name} · v{row.resolution.template_version} · {row.resolution.resolved_locale}</strong><span>{row.resolution.provider_name} · r{row.resolution.provider_revision}</span></div> },
        { title: "Created", dataIndex: "created_at", render: date },
        { title: "", key: "open", render: (_, row) => <Link to={deliveryPath(row.id, returnTo)}>View delivery</Link> },
      ]} /></QueryContent>
  </>;
}

function NotificationDetails({ identifier, session }: { identifier: string; session: Session }) {
  const [params] = useSearchParams();
  const returnTo = notificationReturnPath(params.get("returnTo"));
  const query = useRecords<Detail>(`/notifications/${identifier}`, 2000);
  const item = query.data?.data;
  return <>
    <Link to={returnTo}>← Back to notifications</Link>
    <header className="page-heading"><Typography.Title>Delivery details</Typography.Title><p>Resolved revisions are pinned when the notification is accepted.</p></header>
    {query.error && <Alert type="error" message={errorMessage(query.error)} />}
    {query.isPending && <Skeleton active />}
    {item && <>
      <section className="notification-summary"><div><span className="field-caption">Status</span><State value={item.status} /></div><div><span className="field-caption">Recipient</span><strong>{item.recipient_email ?? item.recipient_mask}</strong></div>
        <div><span className="field-caption">Project / environment</span><strong>{item.resolution.project_name} / {item.resolution.environment_name}</strong></div>
        <div><span className="field-caption">Created / updated</span><span>{date(item.created_at)} / {date(item.updated_at)}</span></div></section>
      {item.status === "retrying" && item.next_attempt_at && <Alert type="info" message={`Next automatic attempt: ${date(item.next_attempt_at)}`} />}
      {item.replay_of_id && <p>Manual replay of <Link to={deliveryPath(item.replay_of_id, returnTo)}>the original delivery</Link>.</p>}
      {item.replay_allowed && <ReplayNotification item={item} session={session} returnTo={returnTo} />}
      {item.error_message && <Alert type={item.status === "unknown" || item.status === "retrying" ? "warning" : "error"} showIcon message={item.error_message} />}
      {item.status === "sent" && <Alert type="success" message={item.channel === "push" ? "Accepted by FCM. Device delivery is not confirmed." : "Accepted by the provider. Inbox delivery is not yet confirmed."} />}
      {item.status === "delivered" && <Alert type="success" message="Delivery confirmed by a verified SES event." />}
      {item.status === "bounced" && <Alert type="warning" message="A verified SES event reported a bounce. The message was not delivered." />}
      <div className="notification-pins"><section><Typography.Title level={3}>Template used</Typography.Title><strong>{item.resolution.template_name}</strong><p>{item.resolution.branch_name} · v{item.resolution.template_version} · {item.resolution.resolved_locale}</p>
        {item.resolution.fallback_used && <Tag>Fallback from {item.locale}</Tag>}</section>
        <section><Typography.Title level={3}>Provider used</Typography.Title><strong>{item.resolution.provider_name} · r{item.resolution.provider_revision}</strong><p>{item.resolution.provider_type.toUpperCase()} · {item.resolution.provider_scope}</p></section></div>
      {!!item.provider_events.length && <><Typography.Title level={2}>Verified provider events</Typography.Title><Table<ProviderEvent> className="directory-table" rowKey="id" dataSource={item.provider_events} pagination={false} columns={[{ title: "Event", dataIndex: "event", render: (value: string) => <State value={value} /> }, { title: "Occurred", dataIndex: "occurred_at", render: date }, { title: "Received", dataIndex: "received_at", render: date }]} /></>}
      <div className="section-heading"><Typography.Title level={2}>Delivery attempts</Typography.Title><Button onClick={() => void query.refetch()}>Refresh delivery</Button></div>
      <Table<Attempt> className="directory-table" rowKey="number" dataSource={item.attempts} pagination={false} locale={{ emptyText: <Empty description="Waiting for the email worker to claim this notification." /> }} columns={[
        { title: "Attempt", dataIndex: "number", render: (value: number) => `#${value}` }, { title: "Outcome", key: "status", render: (_, row) => <State value={row.status} /> },
        { title: "Started", dataIndex: "started_at", render: date }, { title: "Finished", key: "finished", render: (_, row) => row.finished_at ? date(row.finished_at) : "In progress" },
        { title: "Details", key: "details", render: (_, row) => <Space direction="vertical"><span>{row.error_message ?? (row.status === "sent" ? "Provider accepted the message" : "Processing")}</span>{row.provider_message_id && <Typography.Text code>{row.provider_message_id}</Typography.Text>}</Space> },
      ]} />
    </>}
  </>;
}

function ReplayNotification({ item, session, returnTo }: { item: Detail; session: Session; returnTo: string }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState("");
  const [form] = Form.useForm();
  async function submit(values: { current?: boolean; recipient?: string; device_token?: string; context?: string }) {
    setFailure(""); setPending(true);
    try {
      let context: unknown;
      if (!item.payload_available) {
        try { context = JSON.parse(values.context ?? ""); } catch { throw new Error("Enter valid JSON runtime context."); }
        if (!context || typeof context !== "object" || Array.isArray(context)) throw new Error("Runtime context must be a JSON object.");
      }
      const result = await authenticatedRequest<{ id: string }>(session, `/notifications/${item.id}/replay`, "POST", {
        replay_key: key, expected_updated_at: item.updated_at, use_current_deployments: Boolean(values.current),
        ...(!item.payload_available ? { ...(item.channel === "push" ? { device_token: values.device_token } : { recipient: values.recipient }), context } : {}),
      });
      navigate(deliveryPath(result.id, returnTo));
    } catch (error) { setFailure(error instanceof Error ? error.message : errorMessage(error)); }
    finally { setPending(false); }
  }
  return <><p><Button type="primary" onClick={() => { form.resetFields(); setKey(crypto.randomUUID()); setFailure(""); setOpen(true); }}>Replay failed notification</Button></p>
    <Modal title="Replay failed notification" open={open} onCancel={() => setOpen(false)} footer={null} destroyOnClose maskClosable={!pending} closable={!pending}>
      <p>Create a new delivery and keep the original history. Only confirmed failures can be replayed.</p>
      <Form form={form} layout="vertical" onFinish={(values) => void submit(values)}>
        {item.payload_available ? <Alert type="info" message="Reuses the encrypted delivery target and runtime context." description={item.expires_at ? `Runtime input expires ${date(item.expires_at)}.` : undefined} /> : <>
          <Alert type="warning" message="Runtime input has expired. Supply it again to replay." />
          {item.channel === "push" ? <Form.Item name="device_token" label="Device registration token" rules={[{ required: true, min: 16, max: 4096 }]}><Input.Password autoComplete="off" /></Form.Item> : <Form.Item name="recipient" label="Recipient" rules={[{ required: true }, { type: "email" }]}><Input autoComplete="off" /></Form.Item>}
          <Form.Item name="context" label="Runtime context (JSON)" rules={[{ required: true }]}><Input.TextArea rows={5} placeholder="{}" spellCheck={false} /></Form.Item>
        </>}
        <Form.Item name="current" valuePropName="checked"><Checkbox>Use current template and provider deployments</Checkbox></Form.Item>
        <p className="muted-text">By default, the original template and provider revisions stay pinned. Select this after changing a deployment or rotating provider credentials.</p>
        {failure && <Alert type="error" message={failure} />}
        <div className="modal-actions"><Button disabled={pending} onClick={() => setOpen(false)}>Cancel</Button><Button type="primary" htmlType="submit" loading={pending}>Confirm replay</Button></div>
      </Form>
    </Modal>
  </>;
}
