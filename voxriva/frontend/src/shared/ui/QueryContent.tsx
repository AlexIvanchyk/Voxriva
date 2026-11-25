import { Alert, Button, Skeleton } from "antd";
import type { ReactNode } from "react";
import { errorMessage } from "../api/client";

export function QueryContent({ query, children }: { query: { isPending: boolean; error: unknown; refetch: () => Promise<unknown> }; children: ReactNode }) {
  if (query.isPending) return <div role="status" aria-label="Loading results"><Skeleton active /></div>;
  if (query.error) return <Alert showIcon type="error" message="Could not load results" description={errorMessage(query.error)} action={<Button onClick={() => void query.refetch()}>Retry</Button>} />;
  return <>{children}</>;
}
