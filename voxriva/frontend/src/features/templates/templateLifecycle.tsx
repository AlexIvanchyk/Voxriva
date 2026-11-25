import { QueryContent } from "../../shared/ui/QueryContent";
import { BranchesOutlined, CheckCircleOutlined, HistoryOutlined, RocketOutlined } from "@ant-design/icons";
import { Alert, Button, Collapse, Empty, Form, Input, Modal, Select, Space, Table, Tabs, Tag, Typography } from "antd";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { errorMessage } from "../../shared/api/client";
import { Editor } from "../../shared/ui/adminForms";
import type { Session } from "../session/session";
import { authenticatedRequest } from "../session/session";
import { publishVersion, useLifecycleData } from "./api";
import { PublishReview } from "./publishReview";
import { LanguageSelect, languageLabel } from "./templateFields";
import type { Template } from "./types";

import type { Branch, Version } from "./lifecycleTypes";
import { date, label, scopeKey } from "./lifecycleTypes";
import { PublishedPreview } from "./publishedPreview";
import { TemplateDeployments } from "./templateDeployments";
import { VersionDiff } from "./versionHistory";
export function TemplateLifecycle({ item, session, dirty, refresh, onBranch, children }: {
  item: Template; session: Session; dirty: boolean; refresh: () => Promise<unknown>; onBranch: (id: string) => boolean; children: ReactNode;
}) {
  const { base, branches, versions, usage } = useLifecycleData(item);
  const [params] = useSearchParams();
  const [pane, setPane] = useState(params.get("tab") === "deployments" ? "deployments" : "draft");
  const [publish, setPublish] = useState(false);
  const [publishReady, setPublishReady] = useState(false);
  const [addingLanguage, setAddingLanguage] = useState(false);
  const [historyLocale, setHistoryLocale] = useState<string | undefined>(item.locale);
  const [historyBranch, setHistoryBranch] = useState<string>();
  useEffect(() => { setHistoryLocale(item.locale); setHistoryBranch(undefined); }, [item.locale]);
  const [fork, setFork] = useState<Version | null>(null);
  const [preview, setPreview] = useState<Version | null>(null);
  const [notice, setNotice] = useState("");
  const rows = versions.data?.data ?? [];
  const branchRows = branches.data?.data ?? [];
  const locales = [...new Set([item.locale, item.fallback_locale, ...item.languages, ...branchRows.map((row) => row.locale)])];
  const selectedHead = rows.find((row) => row.branch_id === item.branch_id);
  const activeEnvironments = (usage.data?.data.rows ?? []).filter((row) => row.scope === "environment" && row.effective_version);
  const historyRows = rows.filter((row) => (!historyLocale || row.locale === historyLocale) && (!historyBranch || row.branch_id === historyBranch));
  return <>
    <div className="lifecycle-toolbar language-toolbar"><div><span className="field-caption">Editing language</span><Select aria-label="Editing language" value={item.locale} loading={branches.isPending} options={item.languages.map((code) => ({ value: code, label: languageLabel(code) }))} onChange={(locale) => { const branch = branchRows.find((row) => row.locale === locale && row.name === "main") ?? branchRows.find((row) => row.locale === locale); if (branch && onBranch(branch.id)) { setPane("draft"); setNotice(""); } }} /></div>
      <div className="language-status"><Tag>{item.branch_name}</Tag><Tag color={selectedHead ? "blue" : "default"}>{selectedHead ? `Published v${selectedHead.number}` : "Not published"}</Tag><Tag>{item.primary_locale === item.locale ? "Primary language" : "Translation"}</Tag>{selectedHead && <Tag color={dirty || selectedHead.draft_revision !== item.draft_revision ? "orange" : "green"}>{dirty || selectedHead.draft_revision !== item.draft_revision ? "Unpublished changes" : "Matches published version"}</Tag>}</div>
      <Space wrap><Button disabled={!item.editable || dirty} onClick={() => setAddingLanguage(true)}>Add language</Button>{item.editable && item.primary_locale !== item.locale && <Button disabled={dirty} onClick={() => Modal.confirm({ title: `Open ${languageLabel(item.locale)} by default?`, content: "This changes the primary editing language. Delivery fallback is configured separately.", onOk: async () => { await authenticatedRequest(session, `${base}/primary-language`, "PUT", { locale: item.locale, expected_locale: item.primary_locale }); await refresh(); } })}>Set as primary</Button>}{item.editable && <Button type="primary" icon={<CheckCircleOutlined aria-hidden="true" />} disabled={dirty} onClick={() => { setPublishReady(false); setPublish(true); }}>Publish version</Button>}</Space>
    </div>
    <div className="template-usage"><span className="field-caption">Versions in environments</span><Space wrap>{activeEnvironments.slice(0, 2).map((row) => <Tag key={scopeKey(row)}>{row.label} · {row.effective_version!.branch_name} v{row.effective_version!.number} · {row.effective_version!.locale}{row.fallback_used ? " · fallback" : ""}</Tag>)}{activeEnvironments.length > 2 && <Tag>+{activeEnvironments.length-2} environments</Tag>}{!activeEnvironments.length && <span className="muted-text">{usage.isPending ? "Loading deployments…" : usage.error ? "Deployment status unavailable" : "Not deployed to an environment yet"}</span>}<Button size="small" type="link" onClick={() => setPane("deployments")}>View deployments</Button></Space></div>
    <Collapse ghost className="advanced-branches" items={[{ key: "branches", label: "Advanced: branches", children: <Space wrap><Select aria-label="Editing branch" value={item.branch_id} options={branchRows.filter((row) => row.locale === item.locale).map((row) => ({ value: row.id, label: `${row.name}${row.head ? ` · v${row.head.number}` : " · unpublished"}` }))} onChange={(id) => { if (onBranch(id)) setPane("draft"); }} /><Button icon={<BranchesOutlined aria-hidden="true" />} disabled={!item.editable || dirty || !selectedHead} onClick={() => setFork(selectedHead ?? null)}>Create branch</Button><span className="muted-text">Branches are independent drafts within a language.</span></Space> }]} />
    {dirty && <p className="lifecycle-help">Save the draft before publishing or creating another branch.</p>}
    {notice && <Alert type="success" showIcon message={notice} />}
    {(branches.error || versions.error) && <Alert type="error" message={errorMessage(branches.error ?? versions.error)} />}
    <Tabs activeKey={pane} onChange={setPane} className="lifecycle-tabs" items={[
      { key: "draft", label: "Draft editor", children },
      { key: "versions", label: <span><HistoryOutlined aria-hidden="true" /> Version history</span>, children: <>
        <div className="section-heading"><Typography.Title level={2}>Published versions</Typography.Title><span className="muted-text">Immutable snapshots · publishing does not deploy</span></div>
        <div className="directory-toolbar"><Select aria-label="Version language" placeholder="All languages" allowClear value={historyLocale} onChange={(value) => { setHistoryLocale(value); setHistoryBranch(undefined); }} options={locales.map((value) => ({ value, label: languageLabel(value) }))} /><Select aria-label="Version branch" placeholder="All branches" allowClear value={historyBranch} onChange={setHistoryBranch} options={branchRows.filter((row) => !historyLocale || row.locale === historyLocale).map((row) => ({ value: row.id, label: `${row.name} · ${languageLabel(row.locale)}` }))} /></div>
        <QueryContent query={versions}><Table<Version> className="directory-table" rowKey="id" dataSource={historyRows} loading={versions.isPending} pagination={rows.length > 15 ? { pageSize: 15 } : false} scroll={{ x: 850 }}
          locale={{ emptyText: <Empty description="No published versions yet. Save and publish the current draft to begin." /> }} columns={[
            { title: "Version", key: "version", render: (_, row) => <div className="version-identity"><strong>{label(row)}</strong><span>{row.message || "No publication note"}</span></div> },
            { title: "Parent", key: "parent", render: (_, row) => row.parent_version_id ? (rows.find((version) => version.id === row.parent_version_id) ? label(rows.find((version) => version.id === row.parent_version_id)!) : "Source version") : "Initial version" },
            { title: "Published by", dataIndex: "author" }, { title: "Published", key: "date", render: (_, row) => date(row.created_at) },
            { title: "", key: "actions", render: (_, row) => <Space><Button onClick={() => setPreview(row)}>Preview</Button><Button disabled={!item.editable || dirty} onClick={() => setFork(row)}>Branch from version</Button></Space> },
          ]} /></QueryContent>
        <VersionDiff base={base} versions={historyRows} />
      </> },
      { key: "deployments", label: <span><RocketOutlined aria-hidden="true" /> Deployments</span>, children: <TemplateDeployments key={item.locale} item={item} session={session} versions={rows} locales={locales} refresh={async () => { await Promise.all([refresh(), usage.refetch()]); }} /> },
    ]} />
    {addingLanguage && <Editor<{ locale: string; source_branch_id?: string }> title="Add language" description="Create an empty translation or copy an existing saved draft. No publication is required." close={() => setAddingLanguage(false)} submitLabel="Add language" submit={async (values) => {
      const source = branchRows.find((row) => row.id === values.source_branch_id);
      const result = await authenticatedRequest<Branch>(session, `${base}/languages`, "POST", { locale: values.locale, source_branch_id: source?.id ?? null, expected_revision: source?.draft_revision ?? null });
      await branches.refetch(); onBranch(result.id); setPane("draft"); setNotice(`Added ${languageLabel(result.locale)}. Save and publish this translation when ready.`);
    }}><Form.Item name="locale" label="New language" rules={[{ required: true }]}><LanguageSelect label="New language" excluded={item.languages} /></Form.Item><Form.Item name="source_branch_id" label="Starting content" extra="Empty creates a blank draft. Copy uses the selected saved revision, including its variable definitions and test data."><Select allowClear placeholder="Empty draft" options={branchRows.map((row) => ({ value: row.id, label: `${languageLabel(row.locale)} · ${row.name} · saved r${row.draft_revision}` }))} /></Form.Item></Editor>}
    {publish && <Editor<{ message: string }> title="Publish immutable version" description={`Publish the saved ${item.branch_name} draft, revision ${item.draft_revision}, in ${item.locale}. Active deployments will remain unchanged.`}
      close={() => setPublish(false)} submitLabel="Publish version" submitDisabled={dirty || !publishReady} submit={async (values) => {
        const result = await publishVersion(session, item, values.message ?? "");
        await Promise.all([versions.refetch(), branches.refetch(), refresh()]); setNotice(`Published ${label(result)}. Deploy it explicitly when ready.`); setPane("versions");
      }}><PublishReview item={item} previous={selectedHead?.id} session={session} ready={setPublishReady} />
        <Form.Item name="message" label="Publication note" rules={[{ max: 500 }]}><Input.TextArea rows={3} placeholder="Describe what changed" /></Form.Item>
      </Editor>}
    {fork && <Editor<{ source_version_id: string; name: string }> title="Create branch from version"
      description="Start an independent draft from a published snapshot. Changing this branch will not affect its source or any deployment."
      close={() => setFork(null)} submitLabel="Create branch" initial={{ source_version_id: fork.id }} submit={async (values) => {
        const branch = await authenticatedRequest<Branch>(session, `${base}/branches`, "POST", { ...values, locale: fork.locale }); await branches.refetch();
        onBranch(branch.id); setPane("draft"); setNotice(`Created ${branch.name} · ${branch.locale} from a published version.`);
      }}><Form.Item name="source_version_id" label="Published source" rules={[{ required: true }]}><Select options={rows.filter((row) => row.locale === fork.locale).map((row) => ({ value: row.id, label: label(row) }))} /></Form.Item>
        <div className="form-grid"><Form.Item name="name" label="Branch name" rules={[{ required: true, pattern: /^[a-z][a-z0-9/_-]*$/, max: 64 }]}><Input placeholder="e.g. welcome-v2" /></Form.Item>
</div>
      </Editor>}
    {preview && <PublishedPreview base={base} version={preview} session={session} channel={item.channel} close={() => setPreview(null)} />}
  </>;
}

