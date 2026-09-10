import { NavLink, Outlet } from "react-router";
import BackendStatus from "../components/common/BackendStatus";

export default function MainLayout() {
  return (
    <div className="app">
      <header>
        <h1>PDF Brief AI</h1>
        <BackendStatus />

        <nav>
          <NavLink to="/">Home</NavLink>
          <NavLink to="/document">Document</NavLink>
          <NavLink to="/chat">Chat</NavLink>
        </nav>
      </header>

      <Outlet />
    </div>
  );
}
