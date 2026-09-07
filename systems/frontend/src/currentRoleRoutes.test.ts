import { describe, expect, it } from "vitest";
import { currentRoleRedirect } from "./currentRoleRoutes";
import type { AuthUser } from "./types";
const user = (role: string) => ({ status: "active", is_admin: false, active_project_roles: [role], roles: [], active_project_id: "demo", project_scopes: ["demo"] } as unknown as AuthUser);
describe("current role entry policy", () => {
  it.each(["process_engineer", "maintenance_technician", "process_manager"])("redirects retired pages for %s", role => {
    for (const path of ["/backup", "/reference", "/app/projects/demo/blueprint-v2", "/app/projects/demo", "/app"]) {
      expect(currentRoleRedirect(user(role), path, "")).toContain("/app/projects/demo/operations?dashboard=workflow&view=overview");
    }
  });
  it("preserves the current page and selection", () => {
    expect(currentRoleRedirect(user("process_manager"), "/app/projects/demo/operations", "?dashboard=workflow&view=overview&role=process_manager&asset_id=CNC-1")).toBeNull();
    expect(currentRoleRedirect(user("process_engineer"), "/app/projects/demo/operations", "?view=reports&asset_id=CNC-1")).toContain("asset_id=CNC-1");
  });
  it("preserves executive and administrator routes", () => {
    expect(currentRoleRedirect(user("executive_viewer"), "/backup", "")).toBeNull();
    expect(currentRoleRedirect({...user("process_manager"), is_admin: true}, "/admin", "")).toBeNull();
  });
  it("does not redirect pending accounts or accounts without project scopes", () => {
    expect(currentRoleRedirect({...user("process_engineer"), status: "pending_approval"}, "/pending", "")).toBeNull();
    expect(currentRoleRedirect({...user("process_engineer"), active_project_id: null, project_scopes: []}, "/app", "")).toBeNull();
  });
  it("does not retain selection from an unauthorized project", () => {
    const result = currentRoleRedirect(user("process_manager"), "/app/projects/other/operations", "?asset_id=OTHER");
    expect(result).toContain("/app/projects/demo/operations");
    expect(result).not.toContain("OTHER");
  });
});
