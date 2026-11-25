import type { ReactNode } from "react";
import { createContext, useContext } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useRecords } from "../../shared/api/client";

export type ProjectRole = "platform_admin" | "project_admin" | "template_editor" | "operator" | "viewer";
export interface Project { id: string; name: string; role: ProjectRole }
interface Context {
  project?: Project; projects: Project[]; pending: boolean; error: unknown; invalid: boolean;
  select: (id: string) => void; refresh: () => Promise<unknown>;
}
const ProjectContext = createContext<Context | null>(null);
export const canManage = (project?: Project) => project?.role === "platform_admin" || project?.role === "project_admin";
export const canEdit = (project?: Project) => canManage(project) || project?.role === "template_editor";

export function ProjectProvider({ children }: { accountId: string; children: ReactNode }) {
  const query = useRecords<Project[]>("/projects");
  const [params] = useSearchParams();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const projects = query.data?.data ?? [];
  const explicit = params.get("project");
  const project = projects.find((item) => item.id === explicit);
  function select(id: string) {
    const target = pathname.startsWith("/projects/") ? "/projects" : pathname;
    navigate(`${target}?project=${encodeURIComponent(id)}`);
  }
  return <ProjectContext.Provider value={{ project, projects, pending: query.isPending, error: query.error,
    invalid: !!explicit && !project && !query.isPending, select, refresh: query.refetch }}>{children}</ProjectContext.Provider>;
}

export function useProjectContext() {
  const context = useContext(ProjectContext);
  if (!context) throw new Error("Project context is unavailable");
  return context;
}

