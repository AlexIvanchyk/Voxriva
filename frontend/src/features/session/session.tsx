import { LockOutlined } from "@ant-design/icons";
import { Alert, Button, Form, Input, Spin, Typography } from "antd";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError, apiRequest, errorMessage } from "../../shared/api/client";
import { SecondFactor, type Challenge } from "./security";
import { BrandLogo } from "../../shared/ui/BrandLogo";

const { Title } = Typography;

export interface Session {
  account: { id: string; email: string; platform_admin: boolean };
  csrf_token: string;
}

export function authenticatedRequest<T>(session: Session, path: string, method: string, payload?: object) {
  return apiRequest<T>(`/api/v1${path}`, {
    method,
    headers: { "X-CSRF-Token": session.csrf_token },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
}

function SignIn({ onSignIn }: { onSignIn: (session: Session) => void }) {
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [challenge, setChallenge] = useState<Challenge>();

  async function submit(credentials: { email: string; password: string }) {
    setError("");
    setPending(true);
    try {
      const session = await apiRequest<Session | Challenge>("/api/v1/auth/login", {
        method: "POST",
        headers: { "X-Voxriva-Client": "dashboard" },
        body: JSON.stringify(credentials),
      });
      if ("mfa_required" in session) setChallenge(session);
      else onSignIn(session);
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="sign-in-page">
      <div className="sign-in-card">
        <div className="sign-in-brand"><BrandLogo /></div>
        {challenge ? <SecondFactor challenge={challenge} onSignIn={onSignIn} restart={() => { setChallenge(undefined); setError(""); }} /> : <>
        <Title level={1}>Sign in</Title>
        {error && <Alert type="error" showIcon message={error} />}
        <Form layout="vertical" onFinish={submit} requiredMark={false}>
          <Form.Item name="email" label="Email" rules={[{ required: true, type: "email" }]}>
            <Input type="email" autoComplete="username" maxLength={254} />
          </Form.Item>
          <Form.Item name="password" label="Password" rules={[{ required: true }]}>
            <Input.Password autoComplete="current-password" maxLength={256} />
          </Form.Item>
          <Button block type="primary" htmlType="submit" icon={<LockOutlined aria-hidden="true" />} loading={pending}>Sign in</Button>
        </Form>
        </>}
      </div>
    </main>
  );
}

export function SessionGate({ children }: {
  children: (session: Session, signOut: () => Promise<void>) => ReactNode;
}) {
  const [session, setSession] = useState<Session | null>();
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const navigate = useNavigate();
  const location = useLocation();
  const returnTo = location.state?.returnTo;
  const destination = typeof returnTo === "string" && returnTo.startsWith("/") && !returnTo.startsWith("//") ? returnTo : "/";

  useEffect(() => {
    const controller = new AbortController();
    const end = () => setSession(null);
    window.addEventListener("voxriva-session-ended", end);
    apiRequest<Session>("/api/v1/auth/session", {
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(8000)]),
    }).then((view) => {
      if (!controller.signal.aborted) setSession(view);
    }).catch((error) => {
      if (controller.signal.aborted) return;
      if (error instanceof ApiError && error.statusCode === 401) setSession(null);
      else setError(errorMessage(error));
    });
    return () => {
      controller.abort();
      window.removeEventListener("voxriva-session-ended", end);
    };
  }, [attempt]);

  if (error) {
    return <main className="sign-in-page"><div className="sign-in-card">
      <Alert type="error" showIcon message={error} />
      <Button onClick={() => { setError(""); setAttempt(attempt + 1); }}>Try again</Button>
    </div></main>;
  }
  if (session === undefined) return <main className="sign-in-page"><Spin size="large" aria-label="Loading dashboard" /></main>;
  if (session === null) {
    if (location.pathname !== "/sign-in") {
      return <Navigate to="/sign-in" state={{ returnTo: location.pathname + location.search }} replace />;
    }
    return <SignIn onSignIn={(view) => {
      setSession(view);
      navigate(destination, { replace: true });
    }} />;
  }
  if (location.pathname === "/sign-in") return <Navigate to={destination} replace />;
  return children(session, async () => {
    await authenticatedRequest(session, "/auth/logout", "POST");
    setSession(null);
  });
}
