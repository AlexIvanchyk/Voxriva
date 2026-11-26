import { useRecords } from "../../shared/api/client";
import type { Session } from "../session/session";
import { authenticatedRequest } from "../session/session";
import type { Branch, Matrix, Published, Version } from "./lifecycleTypes";
import type { PreviewTarget } from "./layoutPicker";
import type { Template } from "./types";

export function useLifecycleData(item: Template) {
  const base = `/templates/${item.id}`;
  const branches = useRecords<Branch[]>(`${base}/branches`);
  const versions = useRecords<Version[]>(`${base}/versions`);
  const usage = useRecords<Matrix>(`${base}/deployments?locale=${encodeURIComponent(item.locale)}`);
  return { base, branches, versions, usage };
}

export function publishVersion(session: Session, item: Template, message: string, target?: PreviewTarget) {
  return authenticatedRequest<Published>(session, `/templates/${item.id}/publish`, "POST", {
    ...target, branch_id: item.branch_id, expected_revision: item.draft_revision, message,
  });
}
