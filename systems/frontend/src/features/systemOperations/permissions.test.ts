import { describe, expect, it } from "vitest";
import { canCancelSystemJob, canCreateSystemAssetVersion, canCreateSystemJob, canPublishSystemAsset, canReadSystemJobs, canReadSystemOperationalAssets, canValidateSystemAsset } from "./permissions";

describe("system operations permissions", () => {
  it("allows only the dedicated operational asset permission", () => {
    expect(canReadSystemOperationalAssets(["system.assets.read"])).toBe(true);
    expect(canReadSystemOperationalAssets(["admin.access", "admin.users.manage"])).toBe(false);
    expect(canReadSystemOperationalAssets(undefined)).toBe(false);
  });
  it("keeps mapping mutations behind dedicated permissions", () => {
    expect(canCreateSystemAssetVersion(["system.assets.create_version"])).toBe(true);
    expect(canValidateSystemAsset(["system.assets.read"])).toBe(false);
    expect(canPublishSystemAsset(["system.assets.publish"])).toBe(true);
  });
  it("keeps rebuild job operations behind dedicated permissions", () => {
    expect(canReadSystemJobs(["system.jobs.read"])).toBe(true);
    expect(canCreateSystemJob(["system.jobs.read"])).toBe(false);
    expect(canCreateSystemJob(["system.jobs.create"])).toBe(true);
    expect(canCancelSystemJob(["system.jobs.cancel"])).toBe(true);
  });
});
