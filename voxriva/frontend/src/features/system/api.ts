import type { BaseRecord } from "@refinedev/core";
import { useApiUrl, useCustom } from "@refinedev/core";

export interface SystemInfo {
  name: string;
  version: string;
}

export type DependencyState = "ready" | "unavailable" | "unconfigured";

type ContainerState =
  | "created" | "running" | "paused" | "restarting" | "removing"
  | "exited" | "dead" | "completed" | "missing" | "unknown";

type ContainerHealth = "healthy" | "unhealthy" | "starting" | "not_configured" | "unknown";

export interface ContainerStatus {
  service: string;
  name: string | null;
  state: ContainerState;
  health: ContainerHealth;
  restart_count: number | null;
  observed_at: string;
}

interface Snapshot {
  observed_at: string;
  containers: ContainerStatus[];
}

export interface Readiness {
  status: "ready" | "unavailable";
  checks: Record<string, DependencyState>;
}

export interface SystemStatus {
  info: SystemInfo;
  readiness: Readiness;
  monitoring: { status: "current" | "stale" | "unavailable" | "disabled"; snapshot: Snapshot | null };
  snapshot_max_age_seconds: number;
}

export function useSystem<T extends BaseRecord>(resource: "info" | "status" | "readiness") {
  const api = useApiUrl();
  return useCustom<T>({
    url: `${api}/system/${resource}`,
    method: "get",
    queryOptions: { retry: false, refetchInterval: 3000 },
  }).query;
}


