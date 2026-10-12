import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api";


const navItems = [
  { to: "/", end: true, icon: "⌂", label: "课程" },
  { to: "/new", end: false, icon: "+", label: "新建课程" },
  { to: "/workflow", end: false, icon: "⌁", label: "工作流" },
];

export function Layout() {
  const configQuery = useQuery({ queryKey: ["llm-config"], queryFn: api.getLlmConfig });

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <NavLink className="brand" to="/">
          <span className="brand-mark" aria-hidden="true">CA</span>
          <span><strong>Course Agent</strong><small>Local workspace</small></span>
        </NavLink>
        <nav aria-label="主导航" className="side-nav">
          {navItems.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}
              className={({ isActive }) => isActive ? "active" : undefined}>
              <span aria-hidden="true">{item.icon}</span>{item.label}
            </NavLink>
          ))}
        </nav>
        <NavLink className="config-status" to="/new?config=open">
          <span className={`status-dot ${configQuery.data?.configured ? "ready" : ""}`} />
          <span><strong>外部 API 配置</strong><small>
            {configQuery.isPending ? "读取中" : configQuery.data?.configured
              ? `${configQuery.data.model} · 本地` : "DeepSeek · 未配置"}
          </small></span>
          <span aria-hidden="true">⌘</span>
        </NavLink>
      </aside>
      <div className="app-workspace">
        <header className="site-header">
          <p>基于 LLM 的高质量课程生成 Agent</p>
          <span className="local-badge">本地优先</span>
        </header>
        <main className="page">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
