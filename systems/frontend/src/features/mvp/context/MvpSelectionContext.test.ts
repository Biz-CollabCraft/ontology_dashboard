import { describe, expect, it } from "vitest";
import { parseMvpSelection, selectionSearch } from "./MvpSelectionContext";

describe("MVP URL selection contract", () => {
  it("gives URL query precedence over session state", () => {
    const selection = parseMvpSelection({
      projectId: "project-a",
      search: "?view=operations&asset_id=CNC-2&event_id=EVENT-2&role=field_operator&workspace_id=workspace-2",
      defaultRole: "process_manager",
      sessionValue: JSON.stringify({ view: "overview", assetId: "CNC-1", eventId: "EVENT-1", role: "process_manager", workspaceId: "workspace-1" }),
    });
    expect(selection).toEqual({
      projectId: "project-a",
      view: "operations",
      dashboard: "workflow",
      reportTab: "status-map",
      assetId: "CNC-2",
      eventId: "EVENT-2",
      role: "field_operator",
      workspaceId: "workspace-2",
    });
  });

  it("maps unsupported Analysis links to Overview and preserves explicit invalid IDs for a safe empty state", () => {
    const selection = parseMvpSelection({
      projectId: "project-a",
      search: "?view=analysis&asset_id=missing&event_id=missing-event",
      defaultRole: "process_manager",
    });
    expect(selection.view).toBe("overview");
    expect(selection.reportTab).toBe("status-map");
    expect(selection.assetId).toBe("missing");
    expect(selection.eventId).toBe("missing-event");
  });

  it("maps legacy report links to the Reports side tab", () => {
    const selection = parseMvpSelection({
      projectId: "project-a",
      search: "?view=executive-report&asset_id=CNC-2&event_id=EVENT-2",
      defaultRole: "process_manager",
    });
    expect(selection.view).toBe("reports");
    expect(selection.reportTab).toBe("executive-brief");
  });

  it("preserves the overview dashboard variant as a presentation choice", () => {
    const selection = parseMvpSelection({
      projectId: "project-a",
      search: "?view=overview&dashboard=classic",
      defaultRole: "process_manager",
      sessionValue: JSON.stringify({ dashboard: "workflow" }),
    });
    expect(selection.dashboard).toBe("classic");

    const query = selectionSearch(selection);
    expect(new URLSearchParams(query).get("dashboard")).toBe("classic");
  });

  it("serializes a reproducible deep link", () => {
    const query = selectionSearch({
      projectId: "project-a",
      view: "reports",
      dashboard: "workflow",
      reportTab: "inspection-request",
      role: "process_manager",
      workspaceId: "workspace-a",
      assetId: "CNC S01",
      eventId: "EVENT#1",
    });
    const params = new URLSearchParams(query);
    expect(params.get("view")).toBe("reports");
    expect(params.get("dashboard")).toBe("workflow");
    expect(params.get("report")).toBe("inspection-request");
    expect(params.get("asset_id")).toBe("CNC S01");
    expect(params.get("event_id")).toBe("EVENT#1");
  });
});
