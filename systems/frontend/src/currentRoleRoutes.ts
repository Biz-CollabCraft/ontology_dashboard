import type { AuthUser } from "./types";
import { matchOperationsProjectPath, operationsProjectPath } from "./routing";

// UI entry policy only. API authorization and stored role identifiers are unchanged.
export function currentRoleRedirect(user: AuthUser, pathname: string, search: string): string | null {
  if (user.is_admin || user.status !== "active") return null;
  const roles = user.active_project_roles.length ? user.active_project_roles : user.roles;
  if (roles.includes("executive_viewer")) return null;
  if (!roles.some(role => ["process_engineer", "maintenance_technician", "process_manager"].includes(role))) return null;
  const route = matchOperationsProjectPath(pathname);
  const projectId = route && user.project_scopes.includes(route.projectId)
    ? route.projectId : user.active_project_id ?? user.project_scopes[0];
  if (!projectId) return null;
  const role = roles.includes("process_manager") ? "process_manager" : "field_operator";
  const query = new URLSearchParams(route?.projectId === projectId ? search : "");
  const path = operationsProjectPath(projectId);
  if (pathname === path && query.get("dashboard") === "workflow" && query.get("view") === "overview" && query.get("role") === role) return null;
  query.set("dashboard", "workflow");
  query.set("view", "overview");
  query.set("role", role);
  query.delete("report");
  return path + "?" + query.toString();
}
