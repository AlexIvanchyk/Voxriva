import { ConfigProvider } from "antd";
import type { ReactNode } from "react";

export function DashboardTheme({ children }: { children: ReactNode }) {
  return <ConfigProvider theme={{
    token: { colorPrimary: "#3b46b0", borderRadius: 12, fontFamily: "Inter, system-ui, sans-serif" },
    components: { Table: { headerBg: "#f6f7fa", headerColor: "#47536a", rowHoverBg: "#f8faff" } },
  }}>{children}</ConfigProvider>;
}
