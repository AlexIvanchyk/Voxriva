import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";

// Explicit opt-in: this mutates only the dedicated fictional MFA smoke account.
// Traces/screenshots are disabled because enrollment contains live test secrets.
test.use({ trace: "off", screenshot: "off", video: "off", channel: process.env.VOXRIVA_MFA_BROWSER_CHANNEL });
test.skip(process.env.VOXRIVA_MFA_SMOKE !== "1", "Requires an isolated MFA smoke database/account");
const email = "mfa-smoke@example.test";
const password = "Fictional MFA smoke password";

test("enrolls, gates login, recovers once and disables MFA on mobile", async ({ page }) => {
  test.skip(process.env.VOXRIVA_MFA_SMOKE_POLICY === "required");
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/account/security");
  async function passwordLogin() {
    await page.getByLabel("Email", { exact: true }).fill(email);
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
  }
  await passwordLogin();
  await expect(page.getByRole("heading", { name: "Account security" })).toBeVisible();
  await page.getByLabel("Current password").fill(password);
  const setupResponse = page.waitForResponse(r => r.url().endsWith("/auth/mfa/setup"));
  await page.getByRole("button", { name: "Set up authenticator", exact: true }).click();
  const secret = (await (await setupResponse).json()).secret;
  await expect(page.getByText("Or enter this setup key manually", { exact: false })).toBeVisible();
  // Invoke the installed cryptography implementation, never a separate OTP algorithm.
  const code = execFileSync(process.env.VOXRIVA_MFA_PYTHON ?? ".venv/bin/python", ["-c", "import sys,time; from backend.app.features.identity.mfa import totp; print(totp(sys.stdin.read()).generate(int(time.time())).decode())"], { input: secret, cwd: "..", env: { ...process.env, PYTHONPATH: "." } }).toString().trim();
  await page.getByLabel("Authenticator code", { exact: true }).fill(code);
  const confirmation = page.waitForResponse(r => r.url().endsWith("/auth/mfa/confirm"));
  await page.getByRole("button", { name: "Confirm and enable MFA" }).click();
  const codes: string[] = (await (await confirmation).json()).recovery_codes;
  await expect(page.getByRole("button", { name: "Download codes" })).toBeVisible();
  await page.getByRole("button", { name: "I saved my recovery codes" }).click();
  await expect(page.getByText("Multi-factor authentication is enabled", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Menu", exact: true }).click();
  await page.getByRole("dialog", { name: "Navigation" }).getByRole("button", { name: "Sign out", exact: true }).click();
  await passwordLogin();
  await expect(page.getByRole("heading", { name: "Verify your sign-in" })).toBeVisible();
  expect((await page.request.get("/api/v1/projects")).status()).toBe(401);
  await page.getByLabel("Authenticator or recovery code").fill("invalid");
  await page.getByRole("button", { name: "Verify", exact: true }).click();
  await expect(page.getByText("Invalid or already used verification code", { exact: true })).toBeVisible();
  await page.getByLabel("Authenticator or recovery code").fill(codes[0]);
  await page.getByRole("button", { name: "Verify", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Account security" })).toBeVisible();
  await expect(page.getByText(/9 recovery codes remaining/)).toBeVisible();
  await page.getByLabel("Current password").fill(password);
  await page.getByLabel("Authenticator or recovery code").fill(codes[0]);
  await page.getByRole("button", { name: "Disable MFA", exact: true }).click();
  await expect(page.getByText("Invalid or already used verification code", { exact: true })).toBeVisible();
  // Invalid security proof keeps the current page/session mounted.
  await expect(page.getByRole("heading", { name: "Account security" })).toBeVisible();
  await page.getByLabel("Authenticator or recovery code").fill(codes[1]);
  await page.getByRole("button", { name: "Disable MFA", exact: true }).click();
  await expect(page.getByText("Multi-factor authentication is not enabled", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});


test("required policy gates the dashboard until enrollment is confirmed", async ({ page }) => {
  test.skip(process.env.VOXRIVA_MFA_SMOKE_POLICY !== "required");
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/account/security");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Set up multi-factor authentication" })).toBeVisible();
  expect((await page.request.get("/api/v1/auth/session")).status()).toBe(401);
  const setupResponse = page.waitForResponse(r => r.url().endsWith("/auth/mfa/enroll/setup"));
  await page.getByRole("button", { name: "Set up authenticator", exact: true }).click();
  const secret = (await (await setupResponse).json()).secret;
  const code = execFileSync(process.env.VOXRIVA_MFA_PYTHON ?? ".venv/bin/python", ["-c", "import sys,time; from backend.app.features.identity.mfa import totp; print(totp(sys.stdin.read()).generate(int(time.time())).decode())"], { input: secret, cwd: "..", env: { ...process.env, PYTHONPATH: "." } }).toString().trim();
  await page.getByLabel("Authenticator code", { exact: true }).fill(code);
  const enrollmentResponse = page.waitForResponse(r => r.url().endsWith("/auth/mfa/enroll/confirm"));
  await page.getByRole("button", { name: "Verify", exact: true }).click();
  const recovery: string[] = (await (await enrollmentResponse).json()).recovery_codes;
  await expect(page.getByRole("button", { name: "Download codes" })).toBeVisible();
  await page.getByRole("button", { name: "I saved my recovery codes" }).click();
  await expect(page.getByRole("heading", { name: "Account security" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Regenerate recovery codes" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Disable MFA", exact: true })).toHaveCount(0);
  await page.getByLabel("Current password").fill(password);
  await page.getByLabel("Authenticator or recovery code").fill(recovery[0]);
  const replacementResponse = page.waitForResponse(r => r.url().endsWith("/auth/mfa/setup"));
  await page.getByRole("button", { name: "Replace authenticator", exact: true }).click();
  const replacementSecret = (await (await replacementResponse).json()).secret;
  const replacementCode = execFileSync(process.env.VOXRIVA_MFA_PYTHON ?? ".venv/bin/python", ["-c", "import sys,time; from backend.app.features.identity.mfa import totp; print(totp(sys.stdin.read()).generate(int(time.time())).decode())"], { input: replacementSecret, cwd: "..", env: { ...process.env, PYTHONPATH: "." } }).toString().trim();
  await page.getByLabel("Authenticator code", { exact: true }).fill(replacementCode);
  await page.getByRole("button", { name: "Confirm new authenticator", exact: true }).click();
  await expect(page.getByRole("button", { name: "Download codes" })).toBeVisible();
  await page.getByRole("button", { name: "I saved my recovery codes" }).click();
  await expect(page.getByText("Multi-factor authentication is enabled", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
