import type { BaseRecord, DataProvider, HttpError } from "@refinedev/core";
import { useCustom } from "@refinedev/core";

function unsupported(): never {
  throw new Error("This API resource does not support CRUD operations");
}

export class ApiError extends Error implements HttpError {
  constructor(readonly statusCode: number, message: string, readonly details?: unknown) {
    super(message);
  }
}

export async function apiRequest<T>(url: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body) headers.set("Content-Type", "application/json");
  const response = await fetch(url, {
    ...options,
    headers,
    cache: "no-store",
    signal: options.signal ?? AbortSignal.timeout(8000),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    const factorError = url.includes("/auth/mfa") && error?.detail !== "Sign in required" && !String(error?.detail).startsWith("MFA enrollment required");
    if (response.status === 401 && !url.endsWith("/auth/login") && !factorError) {
      window.dispatchEvent(new Event("voxriva-session-ended"));
    }
    throw new ApiError(response.status, typeof error?.detail === "string"
      ? error.detail : typeof error?.detail?.message === "string" ? error.detail.message : Array.isArray(error?.detail)
        ? error.detail.map((entry: { loc?: string[]; msg?: string }) => `${entry.loc?.join(".")}: ${entry.msg}`).join("; ")
        : `Request failed (HTTP ${response.status})`, error?.detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "Could not connect to Voxriva. Try again.";
}

export const dataProvider: DataProvider = {
  getApiUrl: () => "/api/v1",
  getList: unsupported,
  getOne: unsupported,
  create: unsupported,
  update: unsupported,
  deleteOne: unsupported,
  custom: async <T,>({ url, method }: { url: string; method: string }) => ({
    data: await apiRequest<T>(url, { method: method.toUpperCase() }),
  }),
};

export function useRecords<T extends BaseRecord>(path: string, refetchInterval: number | false = false) {
  return useCustom<T>({
    url: `/api/v1${path}`, method: "get", queryOptions: { retry: false, refetchInterval },
  }).query;
}
