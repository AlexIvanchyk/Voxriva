import { Alert, Button, Collapse, Empty, Input, Modal, Select, Slider, Space, Tabs, Tag, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { ApiError, errorMessage } from "../../shared/api/client";
import { isolatedHtml } from "../../shared/lib/previewHtml";
import type { Session } from "../session/session";
import { authenticatedRequest } from "../session/session";
import type { Activate, Diagnostic } from "./templateCode";
import { Code, TextContent } from "./templateCode";
import type { Schema } from "./templateFields";
import { DataFields, VariablesEditor, pretty, propertiesOf } from "./templateFields";
import type { Draft, Template } from "./types";
import { LayoutPicker, type PreviewTarget, type SelectedLayout } from "./layoutPicker";
import { InsertImage, type ImageValue } from "./imageFields";
import { saveOutcome, type SaveAttempt } from "./saveOutcome";

interface Issue { path: (string | number)[]; code: string; message: string }
interface Preview { layout?: SelectedLayout; rendered: Record<string, unknown> | null; errors: Issue[]; diagnostics: Diagnostic[] }
interface Rename { draft: Draft; changes: { field: string; replacements: number }[] }
const fieldLabel: Record<string, string> = { html: "HTML", text: "Plain text", subject: "Subject", title: "Push title", body: "Push message", variable_schema: "Variables" };

export function DraftEditor({ item, session, editable, path, onDirty, onSaved, onTargetChange, active = true }: { onTargetChange?: (target: PreviewTarget) => void; item: Template; session: Session; editable: boolean; path: string; onDirty: (value: boolean) => void; onSaved: () => Promise<unknown>; active?: boolean }) {
  const [draft, setDraft] = useState(item.draft);
  const [revision, setRevision] = useState(item.draft_revision);
  const [saved, setSaved] = useState(pretty(item.draft));
  const [raw, setRaw] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [pending, setPending] = useState(false);
  const [saving, setSaving] = useState(false);
  const [uncertain, setUncertain] = useState<SaveAttempt | null>(null);
  const savingLock = useRef(false);
  const [notice, setNotice] = useState("");
  const [failure, setFailure] = useState("");
  const [pane, setPane] = useState("content");
  const [contentPane, setContentPane] = useState("html");
  const [width, setWidth] = useState(52);
  const [target, setTarget] = useState<PreviewTarget | null>(null);
  const [device, setDevice] = useState(0);
  const [scenario, setScenario] = useState("");
  const [rename, setRename] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [proposal, setProposal] = useState<Rename | null>(null);
  const [renameSource, setRenameSource] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [renameError, setRenameError] = useState("");
  const insert = useRef<((value: string) => void) | null>(null);
  const current = useRef(draft); current.current = draft;
  const saveAction = useRef<() => void>(() => undefined);
  const invalid = Object.keys(errors).length > 0;
  const dirty = pretty(draft) !== saved || invalid || !!uncertain;
  const inherited = preview?.layout?.template_id === draft.layout?.template_id && (!draft.layout?.version_id || preview?.layout?.version_id === draft.layout.version_id) ? preview?.layout : undefined;
  const fields = { ...propertiesOf(inherited?.variable_schema ?? {}), ...propertiesOf(draft.variable_schema) };
  const contextSchema = { ...draft.variable_schema, properties: fields, required: [...(Array.isArray(inherited?.variable_schema.required) ? inherited.variable_schema.required : []), ...(Array.isArray(draft.variable_schema.required) ? draft.variable_schema.required : [])] };
  const variables = Object.keys(fields).filter((value) => /^[A-Za-z][A-Za-z0-9_]*$/.test(value));
  const hasContent = item.channel === "email" ? Boolean(draft.layout || draft.subject || draft.html || draft.text) : Boolean(draft.title || draft.body || Object.keys(draft.data).length);
  const change = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((draft) => ({ ...draft, [key]: value }));
  const activate: Activate = (action) => { insert.current = action; };
  function replace(key: "variable_schema" | "preview_context" | "runtime_defaults", value: Schema) { change(key, value); setRaw((raw) => { const next = { ...raw }; delete next[key]; return next; }); setErrors((errors) => { const next = { ...errors }; delete next[key]; return next; }); }
  useEffect(() => onDirty(dirty || saving || !!uncertain), [dirty, saving, uncertain, onDirty]);
  useEffect(() => {
    const unload = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault(); };
    const navigate = (event: MouseEvent) => { const target = (event.target as Element).closest?.("a[href]"); if (dirty && target instanceof HTMLAnchorElement && new URL(target.href).pathname !== window.location.pathname && !window.confirm("Discard unsaved draft changes and leave the editor?")) { event.preventDefault(); event.stopPropagation(); } };
    window.addEventListener("beforeunload", unload); document.addEventListener("click", navigate, true);
    return () => { window.removeEventListener("beforeunload", unload); document.removeEventListener("click", navigate, true); };
  }, [dirty]);
  useEffect(() => {
    if (!active) return;
    const shortcut = (event: KeyboardEvent) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); saveAction.current(); } };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, [active]);
  useEffect(() => {
    if (invalid || !hasContent) { setPending(false); setPreview(null); return; }
    let canceled = false;
    setPending(true);
    const timer = setTimeout(async () => {
      try { const value = await authenticatedRequest<Preview>(session, `${path}/preview`, "POST", { ...target, branch_id: item.branch_id, ...(editable ? { draft } : {}) }); if (!canceled) { setPreview(value); setPreviewError(""); } }
      catch (error) { if (!canceled) { setPreview(null); setPreviewError(errorMessage(error)); } }
      finally { if (!canceled) setPending(false); }
    }, draft.layout ? 100 : 900);
    return () => { canceled = true; clearTimeout(timer); };
  }, [draft, target, invalid, hasContent, path, editable, item.branch_id, session]);

  async function confirmed(attempt: SaveAttempt, result: Template) {
    setRevision(result.draft_revision); setSaved(pretty(attempt.draft)); setUncertain(null); setFailure("");
    const message = pretty(current.current) === pretty(attempt.draft) ? "Draft saved." : "Snapshot saved. Your newer edits remain unsaved.";
    setNotice(message);
    try { await onSaved(); } catch { setNotice(`${message} Page details could not refresh; your saved draft is confirmed.`); }
  }
  async function reconcile(attempt: SaveAttempt) {
    try {
      const result = await authenticatedRequest<Template>(session, `${path}?branch_id=${encodeURIComponent(attempt.branch)}`, "GET");
      const outcome = saveOutcome(attempt, result);
      if (outcome === "saved") await confirmed(attempt, result);
      else if (outcome === "conflict") {
        setUncertain(null);
        setFailure("The server draft changed. Your local edits are preserved. Copy them before reloading; no newer revision was overwritten.");
      } else setFailure("The save is not confirmed yet. Check its status, or retry the same snapshot safely. Newer local edits are preserved.");
    } catch { setFailure("Could not verify the save result. Your local edits are preserved. Check status before saving another snapshot."); }
  }
  async function checkSave() {
    if (!uncertain || savingLock.current) return;
    savingLock.current = true; setSaving(true);
    try { await reconcile(uncertain); } finally { savingLock.current = false; setSaving(false); }
  }
  async function save(retry?: SaveAttempt) {
    if (!editable || savingLock.current || (!retry && (!dirty || invalid || uncertain))) return;
    const attempt = retry ?? { draft: structuredClone(current.current), revision, branch: item.branch_id };
    savingLock.current = true; setSaving(true); setFailure(""); setNotice("");
    try {
      const result = await authenticatedRequest<Template>(session, `${path}/draft`, "PUT", { draft: attempt.draft, expected_revision: attempt.revision, branch_id: attempt.branch });
      await confirmed(attempt, result);
    } catch (error) {
      if (!(error instanceof ApiError) || error.statusCode >= 500 || (retry && error.statusCode === 409)) {
        setUncertain(attempt); setFailure("Checking whether your draft was saved…"); await reconcile(attempt);
      } else setFailure(errorMessage(error));
    } finally { savingLock.current = false; setSaving(false); }
  }
  saveAction.current = () => void save();
  function json(key: "data" | "variable_schema" | "preview_context" | "runtime_defaults", label: string) { return <Code label={label} value={raw[key] ?? pretty(draft[key])} language="json" readOnly={!editable} height={300} onChange={(value) => { setRaw((raw) => ({ ...raw, [key]: value })); try { const parsed = JSON.parse(value); if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Use a JSON object"); if (key === "data" && Object.values(parsed).some((value) => typeof value !== "string")) throw new Error("Push data values must be strings"); change(key, parsed); setErrors((errors) => { const next = { ...errors }; delete next[key]; return next; }); } catch (error) { setErrors((errors) => ({ ...errors, [key]: error instanceof Error ? error.message : "Invalid JSON" })); } }} />; }
  function advanced(key: "data" | "variable_schema" | "preview_context" | "runtime_defaults", label: string) { return <Collapse className="advanced-json" items={[{ key: "json", label: "Advanced JSON", children: json(key, label) }]} />; }
  const diagnostics = preview?.diagnostics ?? [];
  const rendered = !pending && !invalid && !previewError ? preview?.rendered : null;
  const testErrors = Object.fromEntries((preview?.errors ?? []).filter((issue) => issue.path[0] === "context" && issue.path[1]).map((issue) => [String(issue.path[1]), issue.message]));
  function focusIssue(issue: Diagnostic) { if (issue.field === "variable_schema") setPane("variables"); else { setPane("content"); if (["html", "text"].includes(issue.field)) setContentPane(issue.field); } }
  const code = (field: "html" | "text" | "body") => <Code label={field === "html" ? "Email HTML" : field === "text" ? "Plain text" : "Push body"} language={field === "html" ? "html" : "plaintext"} value={draft[field]} onChange={(value) => change(field, value)} readOnly={!editable} height={460} insertImage={(insert) => <InsertImage images={draft.images ?? {}} inheritedImages={inherited?.images} variables={Object.entries(fields).filter(([, field]) => field["x-voxriva-image"] === 1).map(([name]) => name)} defaults={{ ...inherited?.runtime_defaults, ...draft.runtime_defaults }} insert={insert} change={(images) => change("images", images)} validate={(image) => authenticatedRequest<ImageValue>(session, `${path}/images/validate`, "POST", image)} />} variables={variables} activate={activate} diagnostics={diagnostics.filter((note) => note.field === field)} />;
  return <>
    <div className="draft-savebar"><div><Tag color={dirty || uncertain ? "orange" : "green"}>{saving ? "Saving / checking…" : uncertain ? "Save result unconfirmed" : dirty ? "Unsaved changes" : "Saved draft"}</Tag><span className="muted-text">Revision {revision} · Manual save · Ctrl / ⌘ S</span></div><Button type="primary" aria-label="Save draft" aria-busy={saving} disabled={!editable || !dirty || invalid || !!uncertain} loading={saving} onClick={() => void save()}>Save draft</Button></div>
    {uncertain && <Alert type="warning" message="Save result unconfirmed" description="Your draft remains on this page. A safe retry sends the original snapshot and revision, so it cannot overwrite a newer server revision." action={<Space wrap><Button disabled={saving} onClick={() => void checkSave()}>Check save status</Button><Button disabled={saving || !editable} onClick={() => void save(uncertain)}>Retry same snapshot</Button></Space>} />}
    {notice && <Alert type="success" message={notice} closable onClose={() => setNotice("")} />}{failure && <Alert type="error" message={failure} />}
    {Object.entries(errors).map(([key, message]) => <Alert type="error" key={key} message={`${key}: ${message}`} />)}
    <div className="workspace-controls"><label>Editor width<Slider ariaLabelForHandle="Editor width" min={35} max={70} value={width} onChange={setWidth} /></label><span className="muted-text">Drag to balance editing and preview.</span></div>
    <div className="template-workspace authoring-workspace" style={{ gridTemplateColumns: `minmax(0, ${width}fr) minmax(0, ${100-width}fr)` }}><section className="template-panel">
      <Tabs activeKey={pane} onChange={setPane} items={[
        { key: "content", label: "Content", children: <>
          {item.channel === "email" && (item.is_layout ? <p>Place <code>{"<!-- voxriva:body -->"}</code> once in each format where the email body belongs.</p> : <LayoutPicker session={session} path={path} locale={item.locale} editable={editable} value={draft.layout} change={(value) => change("layout", value)} target={target} chooseTarget={(value) => { setTarget(value); onTargetChange?.(value); }} />)}
          <div className="variable-strip"><span>Variables</span>{variables.map((name) => <Button size="small" key={name} disabled={!editable} onMouseDown={(event) => event.preventDefault()} onClick={() => insert.current?.(`{{ ${name} }}`)}>{`{{ ${name} }}`}</Button>)}{!variables.length && <Button type="link" onClick={() => setPane("variables")}>Define variables</Button>}</div><p className="muted-text">Focus a content field, then click a variable to insert it.</p>
          {item.channel === "email" ? <>{!item.is_layout && <TextContent label="Email subject" value={draft.subject} change={(value) => change("subject", value)} variables={variables} disabled={!editable} activate={activate} />}<Tabs activeKey={contentPane} onChange={setContentPane} items={[{ key: "html", label: "HTML", children: code("html") }, { key: "text", label: "Plain text", children: code("text") }]} /></> : <><TextContent label="Push title" value={draft.title} change={(value) => change("title", value)} variables={variables} disabled={!editable} activate={activate} /><TextContent multiline label="Push body" value={draft.body} change={(value) => change("body", value)} variables={variables} disabled={!editable} activate={activate} /><Typography.Title level={4}>Custom data</Typography.Title><p className="muted-text">String values can contain template variables.</p>{Object.entries(draft.data).map(([key, value]) => <div className="push-data-row" key={key}><code>{key}</code><Input aria-label={`Push data ${key}`} disabled={!editable} value={value} onChange={(event) => change("data", { ...draft.data, [key]: event.target.value })} /><Button disabled={!editable} onClick={() => { const next = { ...draft.data }; delete next[key]; change("data", next); }}>Remove</Button></div>)}<Input.Search aria-label="New push data key" placeholder="New data key" enterButton="Add data" disabled={!editable} onSearch={(key) => { if (key.trim() && !(key.trim() in draft.data)) change("data", { ...draft.data, [key.trim()]: "" }); }} />{advanced("data", "Push data")}</>}
          {diagnostics.filter((note) => !["variable_schema"].includes(note.field)).map((note, index) => <Alert type={note.severity} showIcon key={index} message={`${fieldLabel[note.field] ?? note.field}, line ${note.line}: ${note.message}`} />)}
        </> },
        { key: "variables", label: "Variables", children: <>{inherited && <><h4>Layout variables</h4><VariablesEditor schema={inherited.variable_schema} disabled onChange={() => {}} /><h4>Template variables</h4></>}<VariablesEditor schema={draft.variable_schema} disabled={!editable} onChange={(value) => replace("variable_schema", value)} rename={(name) => { setRename(name); setNewName(name); setProposal(null); setRenameError(""); }} />{diagnostics.filter((note) => note.field === "variable_schema").map((note, index) => <Alert key={index} type={note.severity} message={`${note.name ?? note.path?.join(".") ?? "Variables"}: ${note.message}`} />)}{advanced("variable_schema", "Schema JSON")}</> },
        { key: "fixtures", label: "Test data", children: <><Alert type="info" message="For preview only" description="Use fictional values. Test data and saved scenarios are never sent as delivery context." /><Space wrap className="test-data-actions"><Select aria-label="Preview scenario" placeholder="Load scenario" value={undefined} options={Object.keys(draft.scenarios).map((value) => ({ value, label: value }))} disabled={!editable} onChange={(name: string) => replace("preview_context", draft.scenarios[name])} /><Button disabled={!editable} onClick={() => replace("preview_context", JSON.parse(saved).preview_context)}>Reset test data</Button><Button disabled={!editable} onClick={async () => { const snapshot = draft; try { const result = await authenticatedRequest<Preview>(session, `${path}/preview`, "POST", { ...target, branch_id: item.branch_id, draft, generate_example: true }); if (current.current !== snapshot) { setNotice("Draft changed during generation. Generate again to use the current rules."); return; } if (result.errors.length || !result.rendered?.context) { setFailure(result.errors.map((issue) => issue.message).join("; ") || "Could not generate example."); return; } replace("preview_context", result.rendered.context as Schema); setFailure(""); setNotice("Example generated and validated against the variable contract."); } catch (error) { setFailure(errorMessage(error)); } }}>Generate example</Button></Space>
          <DataFields schema={contextSchema} value={draft.preview_context} onChange={(value) => replace("preview_context", value)} disabled={!editable} errors={testErrors} />{advanced("preview_context", "Fixture JSON")}
          <Space.Compact className="scenario-create"><Input aria-label="Scenario name" value={scenario} maxLength={80} placeholder="Scenario name" disabled={!editable} onChange={(event) => setScenario(event.target.value)} /><Button disabled={!editable || !scenario.trim() || invalid} onClick={() => { change("scenarios", { ...draft.scenarios, [scenario.trim()]: structuredClone(draft.preview_context) }); setScenario(""); }}>Save scenario</Button></Space.Compact>
          <Space wrap>{Object.keys(draft.scenarios).map((name) => <Tag key={name} closable={editable} onClose={() => { const next = { ...draft.scenarios }; delete next[name]; change("scenarios", next); }}>{name}</Tag>)}</Space>
        </> },
        { key: "defaults", label: "Runtime defaults", children: <><Alert type="info" message="Used by real deliveries" description="Set only deliberate defaults. Application context overrides each top-level default; nested objects are replaced as a whole. Missing required values still need to be supplied." />{inherited && <><h4>Layout defaults</h4><DataFields schema={inherited.variable_schema} value={inherited.runtime_defaults} disabled onChange={() => {}} label="Layout default" /><h4>Template defaults</h4></>}<DataFields schema={draft.variable_schema} value={draft.runtime_defaults} onChange={(value) => replace("runtime_defaults", value)} disabled={!editable} label="Runtime default" />{advanced("runtime_defaults", "Runtime defaults JSON")}</> },
      ]} />
    </section><section className="template-panel template-preview" aria-label="Live preview"><div className="section-heading"><Typography.Title level={2}>Live preview</Typography.Title><Select aria-label="Preview device" value={device} onChange={setDevice} options={[{ value: 0, label: "Desktop" }, { value: 375, label: "Mobile · 375px" }, { value: 320, label: "Small phone · 320px" }, { value: 768, label: "Tablet · 768px" }]} /></div>
      {inherited && !pending && <Tag>Layout · {inherited.locale} · {inherited.branch} · v{inherited.number}</Tag>}
      <p className="muted-text">{pending ? "Rendering…" : "Preview only · No notification sent"}</p>{invalid && <Alert type="warning" message="Fix JSON to refresh the preview. Your edits are preserved." />}{!hasContent && <Empty description="Start writing content to see a preview" />}{previewError && <Alert type="error" message={previewError} />}
      {preview?.errors.map((issue, index) => <Alert key={index} type="error" message={`${issue.path.join(".") || issue.code}: ${issue.message}`} action={<Button size="small" onClick={() => { if (issue.path[0] === "context") setPane("fixtures"); else focusIssue({ ...issue, field: String(issue.path[0] ?? "html"), severity: "error", line: Number(issue.path[1]) || 1 }); }}>Show field</Button>} />)}
      {rendered && <div className="preview-viewport" style={{ width: device ? `min(100%, ${device}px)` : "100%" }}>{item.channel === "email" ? <><span className="field-caption">Subject</span><p className="preview-subject">{String(rendered.subject)}</p><Tabs defaultActiveKey={rendered.html ? "html" : "text"} items={[{ key: "html", label: "HTML preview", children: rendered.html ? <iframe title="Email HTML preview" sandbox="" referrerPolicy="no-referrer" srcDoc={isolatedHtml(String(rendered.html), rendered.images)} /> : <Empty description="No HTML content. Open the plain text preview." /> }, { key: "text", label: "Text preview", children: <pre>{String(rendered.text)}</pre> }]} /><small>External resources are blocked. Email clients may render differently.</small></> : <><div className="push-device"><span className="push-clock">9:41</span><div className="push-notification"><small>VOXRIVA · now</small><h3>{String(rendered.title)}</h3><p>{String(rendered.body)}</p></div></div><h4>Custom data</h4><pre>{pretty(rendered.data)}</pre><Tag color={new TextEncoder().encode(JSON.stringify(rendered)).length > 4096 ? "red" : "blue"}>Rendered content: {new TextEncoder().encode(JSON.stringify(rendered)).length} bytes</Tag><p className="muted-text">FCM allows 4096 bytes for the complete request, including the device token and envelope.</p></>}</div>}
    </section></div>
    {rename && <Modal open title={`Rename ${rename}`} closable={!renaming} maskClosable={!renaming} keyboard={!renaming} onCancel={() => setRename(null)} footer={<><Button disabled={renaming} onClick={() => setRename(null)}>Cancel</Button>{proposal ? <Button type="primary" disabled={renameSource !== pretty(draft)} onClick={() => { setDraft(proposal.draft); setRaw({}); setErrors({}); setRename(null); setNotice("Variable renamed in this draft. Save it when ready."); }}>Apply to draft</Button> : <Button type="primary" loading={renaming} disabled={!/^[A-Za-z][A-Za-z0-9_]*$/.test(newName) || newName === rename} onClick={async () => { const snapshot = structuredClone(draft); setRenaming(true); setRenameError(""); try { const result = await authenticatedRequest<Rename>(session, `${path}/variables/rename`, "POST", { draft: snapshot, old_name: rename, new_name: newName }); setProposal(result); setRenameSource(pretty(snapshot)); } catch (error) { setRenameError(errorMessage(error)); } finally { setRenaming(false); } }}>Preview rename</Button>}</>}>
      <p>Updates this draft's variable contract, root references, defaults and saved test data. Published versions remain immutable.</p><label>New variable name<Input aria-label="New variable name" value={newName} disabled={renaming} onChange={(event) => { setNewName(event.target.value); setProposal(null); }} /></label>{renameError && <Alert type="error" message={renameError} />}{proposal && <><Typography.Title level={4}>Reference changes</Typography.Title>{proposal.changes.length ? <ul>{proposal.changes.map((change) => <li key={change.field}>{fieldLabel[change.field] ?? change.field}: {change.replacements} replacement(s)</li>)}</ul> : <p>No content references. The variable definition and saved values will be updated.</p>}{renameSource !== pretty(draft) && <Alert type="warning" message="The draft changed. Preview the rename again before applying it." />}</>}
    </Modal>}
  </>;
}
