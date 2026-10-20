import { NavLink, Outlet } from "react-router-dom";
import { Button, Space } from "antd";
import { useAuth } from "../auth";

export function SiteLayout() {
  const { me, logout } = useAuth();

  return (
    <div className="kp-shell">
      <header className="kp-nav">
        <NavLink to="/" className="kp-brand">
          Keep Password
        </NavLink>
        <nav className="kp-nav-links">
          <NavLink to="/download">下载</NavLink>
          <NavLink to="/docs">文档</NavLink>
          <NavLink to="/security">安全</NavLink>
          <NavLink to="/changelog">更新日志</NavLink>
          {me ? (
            <Space size={8}>
              <NavLink to="/account">个人中心</NavLink>
              {me.isAdmin && <NavLink to="/admin">管理后台</NavLink>}
              <Button size="small" onClick={logout}>
                退出
              </Button>
            </Space>
          ) : (
            <Space size={8}>
              <NavLink to="/login">登录</NavLink>
              <NavLink to="/register">
                <Button type="primary" size="small">
                  注册
                </Button>
              </NavLink>
            </Space>
          )}
        </nav>
      </header>
      <main className="kp-main">
        <Outlet />
      </main>
      <footer className="kp-footer">© Keep Password · 本地优先，可选零知识同步</footer>
    </div>
  );
}
