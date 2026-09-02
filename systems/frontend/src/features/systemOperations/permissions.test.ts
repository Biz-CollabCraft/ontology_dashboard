import { describe, expect, it } from "vitest";
import { canActivateSystemModels, canCancelSystemJob, canCreateImpactAnalysis, canCreateManagedContract, canCreateSystemAssetVersion, canCreateSystemJob, canExecuteSystemRebuild, canPublishManagedContract, canPublishSystemAsset, canReadSystemJobs, canReadSystemModels, canReadSystemOperationalAssets, canRollbackSystemModels, canSelectSystemModels, canValidateManagedContract, canValidateSystemAsset } from "./permissions";

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
  it("separates impact analysis from downstream execution", () => {
    expect(canCreateImpactAnalysis(["system.impact.create"])).toBe(true);
    expect(canExecuteSystemRebuild(["system.impact.create"])).toBe(false);
    expect(canExecuteSystemRebuild(["system.rebuild.execute"])).toBe(true);
  });
  it("keeps model selection and rollback behind dedicated permissions", () => {
    const permissions = ["system.models.read", "system.models.select", "system.models.activate", "system.models.rollback"];
    expect(canReadSystemModels(permissions)).toBe(true);
    expect(canSelectSystemModels(permissions)).toBe(true);
    expect(canActivateSystemModels(permissions)).toBe(true);
    expect(canRollbackSystemModels(permissions)).toBe(true);
    expect(canActivateSystemModels(["admin.users.manage"])).toBe(false);
  });
  it("separates managed contract editing, validation, and publication", () => {
    expect(canCreateManagedContract(["system.contracts.create_version"])).toBe(true);
    expect(canValidateManagedContract(["system.contracts.create_version"])).toBe(false);
    expect(canValidateManagedContract(["system.contracts.validate"])).toBe(true);
    expect(canPublishManagedContract(["system.contracts.validate"])).toBe(false);
    expect(canPublishManagedContract(["system.contracts.publish"])).toBe(true);
  });
});
