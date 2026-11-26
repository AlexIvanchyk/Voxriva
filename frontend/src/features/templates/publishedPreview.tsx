import type { PreviewTarget } from "./layoutPicker";
import { Alert, Button, Input, Modal, Select, Skeleton, Space } from "antd";
import { useEffect, useState } from "react";
import { errorMessage, useRecords } from "../../shared/api/client";
import { isolatedHtml } from "../../shared/lib/previewHtml";
import type { Session } from "../session/session";
import { authenticatedRequest } from "../session/session";

import type { Published, Version } from "./lifecycleTypes";
import { label, pretty } from "./lifecycleTypes";
interface PublishedPreviewProps {
  target?: PreviewTarget; base: string; version: Version; session: Session; channel: string;
}

export function PublishedPreview({ close, ...props }: PublishedPreviewProps & { close: () => void }) {
  const { version } = props;
  return <Modal open centered width={1060} title={`Published preview · ${label(version)}`} onCancel={close} footer={<Button onClick={close}>Close preview</Button>} styles={{ body: { maxHeight: "70dvh", overflowY: "auto" } }}>
    <PublishedVersionContent {...props} />
  </Modal>;
}

export function PublishedVersionContent({ target, base, version, session, channel }: PublishedPreviewProps) {
  const query = useRecords<Published>(`${base}/versions/${version.id}`);
  return <>
    {query.isPending && <Skeleton active />}{query.error && <Alert type="error" message={errorMessage(query.error)} />}
    {query.data && <PublishedPreviewBody target={target} key={version.id} base={base} version={query.data.data} channel={channel} session={session} />}
  </>;
}
function PublishedPreviewBody({ target, base, version, session, channel }: { target?: PreviewTarget; base: string; version: Published; session: Session; channel: string }) {
  const [raw, setRaw] = useState(pretty(version.content.preview_context));
  const [result, setResult] = useState<{ layout?: { locale: string; branch: string; number: number }; rendered: Record<string, unknown> | null; errors: { path: (string | number)[]; message: string }[] } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let canceled = false;
    const timer = setTimeout(async () => {
      try {
        const context = JSON.parse(raw);
        if (!context || Array.isArray(context) || typeof context !== "object") throw new Error("Enter a JSON object for preview variables");
        const response = await authenticatedRequest<typeof result>(session, `${base}/versions/${version.id}/preview`, "POST", { ...target, context });
        if (!canceled) { setResult(response); setError(""); }
      } catch (error) { if (!canceled) { setResult(null); setError(error instanceof SyntaxError || error instanceof Error && !('statusCode' in error) ? error.message : errorMessage(error)); } }
    }, 700);
    return () => { canceled = true; clearTimeout(timer); };
  }, [raw, base, version.id, session, target]);
  const rendered = result?.rendered;
  return <><p className="muted-text">Immutable published content. Changing preview variables sends no notification.</p><div className="published-preview-grid"><div>
    <Space wrap style={{ marginBottom: 14 }}><Select aria-label="Published preview scenario" placeholder="Saved scenario" value={undefined} style={{ minWidth: 170 }} options={Object.keys(version.content.scenarios).map((value) => ({ value, label: value }))} onChange={(name: string) => setRaw(pretty(version.content.scenarios[name]))} /><Button onClick={() => setRaw(pretty(version.content.preview_context))}>Reset variables</Button></Space>
    <label>Preview variables<Input.TextArea aria-label="Published preview variables" rows={12} value={raw} onChange={(event) => setRaw(event.target.value)} /></label>
    <details><summary>Published source</summary><pre className="published-source">{pretty(version.content)}</pre></details></div><div>
    {result?.layout && <p>Layout · {result.layout.locale} · {result.layout.branch} · v{result.layout.number}</p>}
    {error && <Alert type="error" message={error} />}{result?.errors.map((issue, index) => <Alert key={index} type="error" message={`${issue.path.join(".")}: ${issue.message}`} />)}
    {rendered && (channel === "email" ? <><h3>{String(rendered.subject)}</h3><iframe title="Published email preview" sandbox="" referrerPolicy="no-referrer" srcDoc={isolatedHtml(String(rendered.html), rendered.images)} /><pre>{String(rendered.text)}</pre></>
      : <div className="push-device"><span className="push-clock">9:41</span><div className="push-notification"><h3>{String(rendered.title)}</h3><p>{String(rendered.body)}</p></div><pre>{pretty(rendered.data)}</pre></div>)}
    </div></div></>;
}

