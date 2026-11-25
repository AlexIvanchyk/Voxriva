import { Refine } from "@refinedev/core";
import { ProjectProvider } from "../features/projects/projectContext";
import { SessionGate } from "../features/session/session";
import { dataProvider } from "../shared/api/client";
import { Dashboard } from "./layout";
import { DashboardTheme } from "./providers";

export function App() {
  return (
    <DashboardTheme>
      <SessionGate>
        {(session, signOut) => <Refine key={session.account.id} dataProvider={dataProvider} options={{ disableTelemetry: true }}>
          <ProjectProvider accountId={session.account.id}><Dashboard session={session} signOut={signOut} /></ProjectProvider>
        </Refine>}
      </SessionGate>
    </DashboardTheme>
  );
}
