import { Alert, Button, Form, Input, QRCode, Space, Spin, Typography } from "antd";
import { useEffect, useState } from "react";
import { apiRequest, errorMessage } from "../../shared/api/client";
import { authenticatedRequest, type Session } from "./session";

type Setup = { secret: string; uri: string };
export type Challenge = { mfa_required: true; challenge: string; expires_in: number; enrollment_required: boolean };
const header = { "X-Voxriva-Client": "dashboard" };

export function RecoveryCodes({ codes, done }: { codes: string[]; done: () => void }) {
  const [feedback, setFeedback] = useState("");
  function download() {
    const url = URL.createObjectURL(new Blob([`Voxriva recovery codes\nEach code can be used once. Keep these offline.\n\n${codes.join("\n")}\n`], { type: "text/plain" }));
    const link = document.createElement("a"); link.href = url; link.download = "voxriva-recovery-codes.txt"; link.click(); URL.revokeObjectURL(url);
  }
  return <Space direction="vertical" style={{ width: "100%" }}>
    <Alert type="warning" showIcon message="Save your recovery codes now" description="These codes are shown only once. Store them somewhere safe, separate from your authenticator. Each code replaces one authenticator code and works once." />
    <pre aria-label="Recovery codes" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{codes.join("\n")}</pre>
    <Space wrap><Button onClick={() => { void navigator.clipboard.writeText(codes.join("\n")).then(() => setFeedback("Copied")).catch(() => setFeedback("Copy unavailable. Download or select the codes.")); }}>Copy codes</Button><Button onClick={download}>Download codes</Button></Space>
    {feedback && <Typography.Text role="status">{feedback}</Typography.Text>}
    <Button type="primary" onClick={done}>I saved my recovery codes</Button>
  </Space>;
}

function SetupInstructions({ setup }: { setup: Setup }) {
  return <Space direction="vertical" style={{ width: "100%" }}>
    <Typography.Paragraph>In Google Authenticator, Microsoft Authenticator, or another TOTP app, add an account and scan this QR code. Then enter the six-digit code. Setup expires after ten minutes.</Typography.Paragraph>
    <QRCode value={setup.uri} size={200} />
    <Typography.Paragraph>Or enter this setup key manually (time based, SHA1, 6 digits, 30 seconds):</Typography.Paragraph>
    <Typography.Text code copyable style={{ overflowWrap: "anywhere" }}>{setup.secret}</Typography.Text>
  </Space>;
}

export function SecondFactor({ challenge, onSignIn, restart }: { challenge: Challenge; onSignIn: (s: Session) => void; restart: () => void }) {
  const [setup, setSetup] = useState<Setup>();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [codes, setCodes] = useState<string[]>();
  const [session, setSession] = useState<Session>();
  async function start() {
    setPending(true); setError("");
    try { setSetup(await apiRequest<Setup>("/api/v1/auth/mfa/enroll/setup", { method: "POST", headers: header, body: JSON.stringify({ challenge: challenge.challenge }) })); }
    catch (e) { setError(errorMessage(e)); }
    finally { setPending(false); }
  }
  async function verify({ code }: { code: string }) {
    setPending(true); setError("");
    try {
      const body = JSON.stringify({ challenge: challenge.challenge, code: code.trim() });
      if (challenge.enrollment_required) {
        const result = await apiRequest<{ session: Session; recovery_codes: string[] }>("/api/v1/auth/mfa/enroll/confirm", { method: "POST", headers: header, body });
        setCodes(result.recovery_codes); setSession(result.session); setSetup(undefined);
      } else onSignIn(await apiRequest<Session>("/api/v1/auth/mfa/verify", { method: "POST", headers: header, body }));
    } catch (e) { setError(errorMessage(e)); }
    finally { setPending(false); }
  }
  if (codes && session) return <RecoveryCodes codes={codes} done={() => onSignIn(session)} />;
  return <Space direction="vertical" style={{ width: "100%" }}>
    <Typography.Title level={1}>{challenge.enrollment_required ? "Set up multi-factor authentication" : "Verify your sign-in"}</Typography.Title>
    <Typography.Paragraph>{challenge.enrollment_required ? "This installation requires an authenticator before you can access the dashboard." : "Enter a code from your authenticator or one of your saved recovery codes. Used authenticator codes cannot be reused; wait for the next code if needed."} Sign-in verification expires in five minutes.</Typography.Paragraph>
    {error && <Alert type="error" showIcon message={error} />}
    {challenge.enrollment_required && !setup ? <Button type="primary" loading={pending} onClick={() => { void start(); }}>Set up authenticator</Button> : <>
      {setup && <SetupInstructions setup={setup} />}
      <Form layout="vertical" onFinish={verify} requiredMark={false} style={{ width: "100%" }}>
        <Form.Item name="code" label={setup ? "Authenticator code" : "Authenticator or recovery code"} rules={[{ required: true }]}><Input autoFocus autoComplete="one-time-code" maxLength={64} /></Form.Item>
        <Button type="primary" htmlType="submit" loading={pending}>Verify</Button>
      </Form>
    </>}
    <Button onClick={restart} disabled={pending}>Start sign-in again</Button>
    <Typography.Paragraph type="secondary">Lost your device? Use a saved recovery code. If you have none, contact your installation operator for account recovery.</Typography.Paragraph>
  </Space>;
}

type Status = { enabled: boolean; recovery_codes_remaining: number; policy: "optional" | "required" };
export function SecurityPage({ session }: { session: Session }) {
  const [status, setStatus] = useState<Status>();
  const [setup, setSetup] = useState<Setup>();
  const [codes, setCodes] = useState<string[]>();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [form] = Form.useForm();
  async function load() { setStatus(await authenticatedRequest<Status>(session, "/auth/mfa", "GET")); }
  useEffect(() => { void authenticatedRequest<Status>(session, "/auth/mfa", "GET").then(setStatus).catch(e => setError(errorMessage(e))); }, [session]);
  async function submit(values: { password: string; code: string; action?: string }) {
    setPending(true); setError("");
    try {
      if (setup) {
        const result = await authenticatedRequest<{ recovery_codes: string[] }>(session, "/auth/mfa/confirm", "POST", { code: values.code.trim() });
        setSetup(undefined); setCodes(result.recovery_codes);
      } else if (!status?.enabled || values.action === "replace") {
        setSetup(await authenticatedRequest<Setup>(session, "/auth/mfa/setup", "POST", { password: values.password, code: values.code?.trim() ?? "" }));
      } else {
        const result = await authenticatedRequest<{ recovery_codes: string[] } | undefined>(session, values.action === "disable" ? "/auth/mfa/disable" : "/auth/mfa/recovery-codes", "POST", { password: values.password, code: values.code.trim() });
        if (result) setCodes(result.recovery_codes);
      }
      form.resetFields(); await load();
    } catch (e) { setError(errorMessage(e)); }
    finally { setPending(false); }
  }
  return <section style={{ maxWidth: 640 }}>
    <Typography.Title level={1}>Account security</Typography.Title>
    <Typography.Paragraph>Protect your account with an authenticator app. Keep recovery codes offline in case you lose your device.</Typography.Paragraph>
    {error && <Alert type="error" showIcon message={error} />}
    {!status ? (error ? <Button onClick={() => { setError(""); void load().catch(e => setError(errorMessage(e))); }}>Retry security settings</Button> : <Spin aria-label="Loading security settings" />) : codes ? <RecoveryCodes codes={codes} done={() => setCodes(undefined)} /> : <>
      <Alert showIcon type={status.enabled ? "success" : "info"} message={status.enabled ? "Multi-factor authentication is enabled" : "Multi-factor authentication is not enabled"} description={status.enabled ? `${status.recovery_codes_remaining} recovery codes remaining. ${status.policy === "required" ? "Your installation requires MFA." : ""}` : "Use Google Authenticator or any compatible TOTP app."} />
      {setup && <SetupInstructions setup={setup} />}
      {status.enabled && <Typography.Paragraph>To regenerate recovery codes, enter your password and a fresh authenticator code or unused recovery code. Regeneration replaces all old recovery codes. Replacing an authenticator keeps the current device active until you confirm the new device, then replaces all recovery codes. Authenticator codes are one-time; after signing in, wait for the next code. Other dashboard sessions are signed out after security changes.</Typography.Paragraph>}
      <Form form={form} layout="vertical" onFinish={submit} requiredMark={false}>
        {!setup && <Form.Item name="password" label="Current password" rules={[{ required: true }]}><Input.Password autoComplete="current-password" maxLength={256} /></Form.Item>}
        {(setup || status.enabled) && <Form.Item name="code" label={setup ? "Authenticator code" : "Authenticator or recovery code"} rules={[{ required: true }]}><Input autoComplete="one-time-code" maxLength={64} /></Form.Item>}
        <Space wrap><Button type="primary" htmlType="submit" loading={pending}>{setup ? (status.enabled ? "Confirm new authenticator" : "Confirm and enable MFA") : status.enabled ? "Regenerate recovery codes" : "Set up authenticator"}</Button>
          {status.enabled && !setup && <Button loading={pending} onClick={() => { void form.validateFields().then(values => submit({ ...values, action: "replace" })); }}>Replace authenticator</Button>}
          {status.enabled && !setup && status.policy === "optional" && <Button danger loading={pending} onClick={() => { void form.validateFields().then(values => submit({ ...values, action: "disable" })); }}>Disable MFA</Button>}
          {setup && <Button disabled={pending} onClick={() => { setSetup(undefined); form.resetFields(); }}>Cancel setup</Button>}
        </Space>
      </Form>
      <Typography.Paragraph type="secondary">To replace an authenticator, enter your current password and authenticator or recovery code, then choose Replace authenticator. If your device and all recovery codes are lost, contact the installation operator.</Typography.Paragraph>
    </>}
  </section>;
}
