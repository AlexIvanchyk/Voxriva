import { ApiOutlined, BarsOutlined, CloudServerOutlined, DashboardOutlined, DeploymentUnitOutlined, FileTextOutlined, FolderOutlined, GlobalOutlined, KeyOutlined, LogoutOutlined, MenuOutlined, TeamOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { Button, Drawer, Layout, message } from "antd";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import type { Session } from "../features/session/session";
import { errorMessage } from "../shared/api/client";
import { BrandLogo } from "../shared/ui/BrandLogo";
import { DashboardRoutes } from "./routes";
const { Content } = Layout;

export function Dashboard({ session, signOut }: { session: Session; signOut: () => Promise<void> }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuTrigger = useRef<HTMLElement | null>(null);
  const focusContent = useRef(false);
  const location = useLocation();
  useEffect(() => { setMenuOpen(false); focusContent.current = true; }, [location.pathname, location.search]);
  useEffect(() => { const media = window.matchMedia("(max-width: 760px)"); const resize = () => { if (!media.matches) setMenuOpen(false); }; media.addEventListener("change", resize); return () => media.removeEventListener("change", resize); }, []);
  const [logoutPending, setLogoutPending] = useState(false);
  const [feedback, holder] = message.useMessage();
  const platformAdmin = session.account.platform_admin;

  async function logout() {
    setLogoutPending(true);
    try { await signOut(); }
    catch (error) { void feedback.error(errorMessage(error)); }
    finally { setLogoutPending(false); }
  }

  const navigation = <>
      <nav aria-label="Main navigation">
        <NavLink to="/" end><DashboardOutlined aria-hidden="true" /> Overview</NavLink>
        <span className="nav-group-label">Content</span>
        <NavLink to="/templates"><FileTextOutlined aria-hidden="true" /> Templates</NavLink>
        <NavLink to="/deployments"><DeploymentUnitOutlined aria-hidden="true" /> Deployments</NavLink>
        <span className="nav-group-label">Delivery</span>
        <NavLink to="/notifications"><ThunderboltOutlined aria-hidden="true" /> Notifications</NavLink>
        <NavLink to="/operations"><BarsOutlined aria-hidden="true" /> Operations</NavLink>
        <NavLink to="/providers"><ApiOutlined aria-hidden="true" /> Providers</NavLink>
        <span className="nav-group-label">Workspace</span>
        <NavLink to="/projects"><FolderOutlined aria-hidden="true" /> Projects</NavLink>
        <NavLink to="/environments"><GlobalOutlined aria-hidden="true" /> Environments</NavLink>
        <NavLink to="/members"><TeamOutlined aria-hidden="true" /> Members</NavLink>
        <NavLink to="/api-keys"><KeyOutlined aria-hidden="true" /> API keys</NavLink>
        {platformAdmin && <span className="nav-group-label">Installation</span>}
        {platformAdmin && <NavLink to="/system/health"><CloudServerOutlined aria-hidden="true" /> System Health</NavLink>}
      </nav>
      <div className="sidebar-account">
        <Link to="/account/security">Account security</Link>
        <span className="account-email" title={session.account.email}>{session.account.email}</span>
        <Button type="text" onClick={logout} loading={logoutPending} icon={<LogoutOutlined aria-hidden="true" />}>Sign out</Button>
      </div>
  </>;

  return <Layout className="app">
    {holder}
    <a className="skip-link" href="#main-content">Skip to content</a>
    <header className="mobile-header"><Link to="/" aria-label="Voxriva home"><BrandLogo /></Link><Button aria-expanded={menuOpen} aria-controls="mobile-navigation" icon={<MenuOutlined aria-hidden="true" />} onClick={(event) => { menuTrigger.current = event.currentTarget; focusContent.current = false; setMenuOpen(true); }}>Menu</Button></header>
    <Drawer aria-label="Navigation" title="Navigation" placement="left" width="min(320px, 90vw)" open={menuOpen} onClose={() => setMenuOpen(false)} rootClassName="mobile-navigation" afterOpenChange={(open) => { if (!open) queueMicrotask(() => { if (focusContent.current) document.getElementById("main-content")?.focus(); else if (menuTrigger.current?.getClientRects().length) menuTrigger.current.focus(); else document.getElementById("main-content")?.focus(); }); }}><div id="mobile-navigation" className="sidebar drawer-sidebar" onClickCapture={(event) => { if ((event.target as Element).closest("a[href]") && !event.defaultPrevented && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) { focusContent.current = true; setMenuOpen(false); } }}>{navigation}</div></Drawer>
    <aside className="sidebar">
      <Link to="/" className="brand">
        <BrandLogo />
      </Link>
      {navigation}
    </aside>
    <Content className="content" id="main-content" tabIndex={-1}>
      <div className="content-frame">
        <DashboardRoutes session={session} />
      </div>
    </Content>
  </Layout>;
}

