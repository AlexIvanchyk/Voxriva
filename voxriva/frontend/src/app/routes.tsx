import { Alert, Skeleton, Typography } from "antd";
import { lazy, Suspense } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { DeploymentsPage } from "../features/deployments/deployments";
import { MembersPage } from "../features/members/members";
import { NotificationsPage } from "../features/notifications/notifications";
import { OperationsPage } from "../features/notifications/operations";
import { ProjectPage, ProjectsPage } from "../features/projects/administration";
import { ApiKeysPage, LegacyKeysPage } from "../features/projects/apiKeys";
import { EnvironmentsPage } from "../features/projects/environments";
import { ProvidersPage } from "../features/providers/providers";
import { SecurityPage } from "../features/session/security";
import type { Session } from "../features/session/session";
import { Overview, SystemHealth } from "../features/system/SystemPages";
const TemplatesPage = lazy(() => import("../features/templates/templates").then((module) => ({ default: module.TemplatesPage })));
const TemplateEditorPage = lazy(() => import("../features/templates/templates").then((module) => ({ default: module.TemplateEditorPage })));
const { Title } = Typography;

export function DashboardRoutes({ session }: { session: Session }) {
  const platformAdmin = session.account.platform_admin;
  const { pathname } = useLocation();
  return <Suspense fallback={<Skeleton active />}><Routes key={pathname}>
          <Route path="/account/security" element={<SecurityPage session={session} />} />
          <Route path="/" element={<Overview platformAdmin={platformAdmin} />} />
          <Route path="/system/health" element={platformAdmin ? <SystemHealth /> : (
            <Alert showIcon type="error" message="Platform administrator access required" />
          )} />
          <Route path="/templates" element={<TemplatesPage session={session} />} />
          <Route path="/templates/:templateId" element={<TemplateEditorPage session={session} />} />
          <Route path="/notifications" element={<NotificationsPage session={session} />} />
          <Route path="/notifications/:notificationId" element={<NotificationsPage session={session} />} />
          <Route path="/operations" element={<OperationsPage />} />
          <Route path="/providers" element={<ProvidersPage session={session} />} />
          <Route path="/deployments" element={<DeploymentsPage />} />
          <Route path="/projects" element={<ProjectsPage session={session} />} />
          <Route path="/projects/:projectId" element={<ProjectPage />} />
          <Route path="/environments" element={<EnvironmentsPage session={session} />} />
          <Route path="/members" element={<MembersPage session={session} />} />
          <Route path="/api-keys" element={<ApiKeysPage session={session} />} />
          <Route path="/projects/:projectId/environments/:environmentId" element={<LegacyKeysPage />} />
          <Route path="*" element={<Title level={1}>Page not found</Title>} />
        </Routes></Suspense>;
}
