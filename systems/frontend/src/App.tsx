import { lazy, Suspense, useEffect } from "react";
import { AuthProvider, useAuth } from "./features/auth/AuthContext";
import { DisplayPreferencesProvider } from "./ui/foundry/displayPreferences";
import { I18nProvider } from "./ui/i18n/I18nProvider";
import { navigate, loginPath, usePathname, matchOperationsProjectPath, operationsProjectPath } from "./routing";

const LoginPage = lazy(() => import("./features/auth/LoginPage").then(m => ({default: m.LoginPage})));
const RegisterPage = lazy(() => import("./features/auth/RegisterPage").then(m => ({default: m.RegisterPage})));
const PendingPage = lazy(() => import("./features/auth/PendingPage").then(m => ({default: m.PendingPage})));
const AdminApp = lazy(() => import("./features/admin/AdminApp").then(m => ({default: m.AdminApp})));
const Factory = lazy(() => import("./features/operations/overview/EngineerFactoryApplication"));

function Redirect({ to }: { to: string }) {
  useEffect(() => { const timer = window.setTimeout(() => navigate(to, {replace: true}), 0); return () => window.clearTimeout(timer); }, [to]);
  return <p role="status">업무 화면으로 이동 중입니다.</p>;
}
function Router() {
  const pathname = usePathname();
  const { user, loading, logout } = useAuth();
  if (loading) return <p role="status">로그인 정보를 확인하고 있습니다.</p>;
  if (!user) {
    if (pathname === "/register") return <RegisterPage />;
    if (pathname === "/pending") return <PendingPage />;
    if (pathname !== "/" && pathname !== "/login") return <Redirect to={loginPath(pathname + window.location.search)} />;
    return <LoginPage />;
  }
  if (user.is_admin) return <AdminApp />;
  if (user.status !== "active") return <PendingPage />;
  const roles = user.active_project_roles.length ? user.active_project_roles : user.roles;
  const allowed = roles.some(role => ["process_engineer", "maintenance_technician", "process_manager"].includes(role));
  const route = matchOperationsProjectPath(pathname);
  const projectId = route && user.project_scopes.includes(route.projectId) ? route.projectId : user.active_project_id ?? user.project_scopes[0];
  if (!allowed || !projectId || !user.project_scopes.includes(projectId)) return <main><h1>사용 가능한 업무 화면이 없습니다.</h1><p>현재 엔지니어·보전팀·생산 관리자 화면만 제공합니다. 계정 권한은 관리자에게 문의해 주세요.</p><button onClick={() => void logout().then(() => navigate("/login", {replace: true}))}>로그아웃</button></main>;
  const query = new URLSearchParams(route?.projectId === projectId ? window.location.search : "");
  const role = roles.includes("process_manager") ? "process_manager" : "field_operator";
  const workspace = query.get("workspace_id");
  if (workspace && !user.workspace_scopes.includes(workspace)) return <main><p>이 작업 공간에 접근할 권한이 없습니다.</p><button onClick={() => navigate(operationsProjectPath(projectId) + "?dashboard=workflow&view=overview&role=" + role)}>업무 화면으로</button></main>;
  if (pathname !== operationsProjectPath(projectId) || query.get("dashboard") !== "workflow" || query.get("view") !== "overview" || query.get("role") !== role) {
    query.set("dashboard", "workflow"); query.set("view", "overview"); query.set("role", role); query.delete("report");
    return <Redirect to={operationsProjectPath(projectId) + "?" + query.toString()} />;
  }
  return <Factory key={projectId} projectId={projectId} />;
}
function ScopedRouter() {
  const {user} = useAuth();
  return <DisplayPreferencesProvider key={user?.user_id ?? "guest"} scope={user?.user_id ?? "guest"}><Suspense fallback={<p role="status">화면을 준비하고 있습니다.</p>}><Router /></Suspense></DisplayPreferencesProvider>;
}
export default function App() {
  return <I18nProvider><AuthProvider><ScopedRouter /></AuthProvider></I18nProvider>;
}
