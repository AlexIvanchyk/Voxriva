import { Alert, Input, Modal, Select, Space, Tabs, Typography } from "antd";
import { useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage, useRecords } from "../../shared/api/client";

interface Scope { id: string; name: string; project: { id: string; name: string } }
interface Template { id: string; name: string; key: string; channel: "email" | "push" }
const shell = (value: string) => "'" + value.replaceAll("'", "'\\''") + "'";
const py = (value: string) => JSON.stringify(value);

export function IntegrationExamples({ scope, close, pendingSecret = false }: { scope: Scope; close: () => void; pendingSecret?: boolean }) {
  const query = useRecords<Template[]>(`/templates?project_id=${scope.project.id}`);
  const [channel, setChannel] = useState<"email" | "push">("email");
  const [templateKey, setTemplateKey] = useState<string>();
  const [locale, setLocale] = useState("en");
  const template = templateKey ?? "<template-key>";
  const target = channel === "email" ? { recipient: "person@example.test" } : { device_token: "<device-registration-token>" };
  const payload = { template_key: template, ...target, locale, context: { "<required-variable>": "<runtime-value>" } };
  const base = window.location.origin;
  const args = channel === "email" ? 'recipient="person@example.test"' : 'device_token=os.environ["FCM_DEVICE_TOKEN"]';
  const curl = (validate: boolean) => [
    `curl --request POST ${shell(`${base}/api/v1/notifications${validate ? "/validate" : ""}`)}`,
    "--header 'Authorization: Bearer <environment-api-key>'",
    ...(validate ? [] : ["--header 'Idempotency-Key: <stable-request-id>'"]),
    "--header 'Content-Type: application/json'",
    `--data ${shell(JSON.stringify(payload, null, 2))}`,
  ].join(" \\" + "\n  ");
  const sync = `import os
from voxriva_sdk import Client

context = {"<required-variable>": "<runtime-value>"}
with Client(${py(base)}, os.environ["VOXRIVA_API_KEY"]) as client:
    client.validate(${py(template)}, ${args}, locale=${py(locale)}, context=context)
    accepted = client.send(
        ${py(template)}, ${args}, locale=${py(locale)}, context=context,
        idempotency_key="<stable-request-id>",
    )
    print(accepted.id, accepted.dashboard_url)
    delivery = client.get_notification(accepted.id)
    print(delivery.status.value)`;
  const async = `import asyncio
import os
from voxriva_sdk import AsyncClient

async def main():
    async with AsyncClient(${py(base)}, os.environ["VOXRIVA_API_KEY"]) as client:
        accepted = await client.send(
            ${py(template)}, ${args}, locale=${py(locale)},
            context={"<required-variable>": "<runtime-value>"},
            idempotency_key="<stable-request-id>",
        )
        print(accepted.dashboard_url)
        delivery = await client.get_notification(accepted.id)
        print(delivery.status.value)

asyncio.run(main())`;
  function code(value: string) { return <><Typography.Paragraph copyable={{ text: value }}>Copy example</Typography.Paragraph><pre className="integration-code"><code>{value}</code></pre></>; }
  return <Modal open title="Integration examples" width={900} onCancel={close} footer={null} className="integration-dialog">
    <p><strong>{scope.project.name} / {scope.name}</strong> · Environment <Typography.Text code>{scope.id}</Typography.Text></p>
    <Alert type="info" showIcon message="Use an API key issued for this environment" description="Replace all placeholders and provide the actual published template's runtime values. Preview data is never substituted. Examples never include a saved API key and do not send anything from this screen." />
    <div className="integration-filters"><Select aria-label="Integration channel" value={channel} onChange={(value) => { setChannel(value); setTemplateKey(undefined); }} options={[{ value: "email", label: "Email" }, { value: "push", label: "Push" }]} />
      <Select aria-label="Integration template" placeholder="Choose a connected template" allowClear showSearch optionFilterProp="label" value={templateKey} onChange={setTemplateKey} options={(query.data?.data ?? []).filter((item) => item.channel === channel).map((item) => ({ value: item.key, label: `${item.name} · ${item.key}` }))} />
      <Input aria-label="Integration locale" value={locale} onChange={(event) => setLocale(event.target.value)} placeholder="Locale" maxLength={35} /></div>
    {query.error && <Alert type="error" message={errorMessage(query.error)} />}
    <p className="muted-text">The template must be published and deployed here, with a provider assigned to its channel. Use an empty context object if no runtime variables are required.</p>
    <Space wrap className="integration-links"><a href="/downloads/voxriva_sdk-0.1.1-py3-none-any.whl" download>Download Python SDK</a><a href="/downloads/delivery-v1.openapi.json" download>OpenAPI v1</a>{pendingSecret ? <span>Close examples and choose Done after saving your key to open history.</span> : <Link to={`/notifications?project=${scope.project.id}&environment=${scope.id}`}>Open environment history</Link>}</Space>
    <Tabs items={[{ key: "curl", label: "curl", children: code(curl(false)) }, { key: "python", label: "Python", children: <><p className="muted-text">Install the downloaded wheel: <code>python -m pip install /path/to/voxriva_sdk-0.1.1-py3-none-any.whl</code>. Set VOXRIVA_API_KEY in your application's environment.</p>{code(sync)}</> },
      { key: "async", label: "Python async", children: code(async) }, { key: "validate", label: "Validate only", children: <><p>Checks current input and deployments without creating a notification or contacting a provider. Send resolves deployments again at acceptance.</p>{code(curl(true))}</> }]} />
    <p className="muted-text">Keep the same business-operation key and payload when retrying. Sent confirms provider acceptance; verified events are needed for Delivered. The returned SDK dashboard_url opens the specific record after dashboard sign-in.</p>
  </Modal>;
}
