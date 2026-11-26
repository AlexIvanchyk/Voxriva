import type { PreviewTarget } from "./layoutPicker";
import { Alert, Button, Skeleton, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import { apiRequest, errorMessage } from "../../shared/api/client";
import type { Session } from "../session/session";
import { authenticatedRequest } from "../session/session";
import { contentChanges, languageLabel } from "./templateFields";
import type { Draft, Template } from "./types";

export function PublishReview({ target, item, previous, session, ready }: { target?: PreviewTarget; item: Template; previous?: string; session: Session; ready: (value: boolean) => void }) {
  const [report, setReport] = useState<{ errors: string[]; warnings: string[]; changes: string[] } | null>(null);
  const [failure, setFailure] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let canceled = false; ready(false); setReport(null); setFailure("");
    async function check() {
      try {
        const [preview, old] = await Promise.all([authenticatedRequest<{ errors: { message: string }[]; diagnostics: { severity: string; message: string }[] }>(session, `/templates/${item.id}/preview`, "POST", { ...target, branch_id: item.branch_id }), previous ? apiRequest<{ content: Draft }>(`/api/v1/templates/${item.id}/versions/${previous}`) : Promise.resolve(null)]);
        const errors = preview.errors.map((issue) => issue.message);
        if (item.channel === "email" && ((!item.is_layout && !item.draft.subject.trim()) || !(item.draft.html.trim() || item.draft.text.trim()))) errors.unshift("Complete the subject and HTML or plain text.");
        if (item.channel === "push" && (!item.draft.title.trim() || !item.draft.body.trim())) errors.unshift("Complete the push title and message.");
        if (!canceled) { setReport({ errors, warnings: (preview.diagnostics ?? []).filter((issue) => issue.severity === "warning").map((issue) => issue.message), changes: old ? contentChanges(old.content, item.draft) : [] }); ready(errors.length === 0); }
      } catch (error) { if (!canceled) { setFailure(errorMessage(error)); ready(false); } }
    }
    void check(); return () => { canceled = true; };
  }, [target, item.id, item.branch_id, item.draft_revision, item.draft, previous, session, ready, attempt, item.channel, item.is_layout]);
  return <><div className="publication-context"><Tag>{languageLabel(item.locale)}</Tag><Tag>{item.branch_name}</Tag><span>Saved revision {item.draft_revision}</span></div>
    {!report && !failure && <Skeleton active paragraph={{ rows: 2 }} />}
    {failure && <Alert type="error" message={failure} action={<Button onClick={() => setAttempt((value) => value+1)}>Retry checks</Button>} />}
    {report && <><Alert type={report.errors.length ? "error" : "success"} showIcon message={report.errors.length ? "Resolve these issues before publishing" : "Saved draft passed publication checks"} description={report.errors.length ? <ul>{report.errors.map((message, index) => <li key={index}>{message}</li>)}</ul> : "Content and runtime validation passed using the saved test data."} />
      <Typography.Title level={5}>Change summary</Typography.Title>{!previous ? <p>First publication for this language and branch.</p> : report.changes.length ? <ul>{report.changes.map((value) => <li key={value}>{value}</li>)}</ul> : <p>No content or variable-contract changes from the previous version.</p>}
      {!!report.warnings.length && <Alert type="warning" message="Review warnings" description={<ul>{report.warnings.map((message, index) => <li key={index}>{message}</li>)}</ul>} />}</>}
  </>;
}
