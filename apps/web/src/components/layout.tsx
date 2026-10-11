import { NavLink, Outlet } from "react-router-dom";

export function Layout() {
  return (
    <div className="app-shell">
      <header className="site-header">
        <NavLink className="brand" to="/">
          AI Course Studio
        </NavLink>
        <nav aria-label="主导航">
          <NavLink to="/" end>
            课程
          </NavLink>
          <NavLink to="/workflow">工作流</NavLink>
          <NavLink to="/new">新建课程</NavLink>
        </nav>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </div>
  );
}
