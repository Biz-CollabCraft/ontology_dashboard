export const SYSTEM_ASSETS_READ_PERMISSION = "system.assets.read";
export const SYSTEM_ASSETS_CREATE_VERSION_PERMISSION = "system.assets.create_version";
export const SYSTEM_ASSETS_VALIDATE_PERMISSION = "system.assets.validate";
export const SYSTEM_ASSETS_PUBLISH_PERMISSION = "system.assets.publish";
export const SYSTEM_JOBS_READ_PERMISSION = "system.jobs.read";
export const SYSTEM_JOBS_CREATE_PERMISSION = "system.jobs.create";
export const SYSTEM_JOBS_CANCEL_PERMISSION = "system.jobs.cancel";
export const SYSTEM_IMPACT_READ_PERMISSION = "system.impact.read";
export const SYSTEM_IMPACT_CREATE_PERMISSION = "system.impact.create";
export const SYSTEM_REBUILD_EXECUTE_PERMISSION = "system.rebuild.execute";
export const SYSTEM_CONTRACTS_READ_PERMISSION = "system.contracts.read";
export const SYSTEM_CONTRACTS_CREATE_PERMISSION = "system.contracts.create_version";
export const SYSTEM_CONTRACTS_VALIDATE_PERMISSION = "system.contracts.validate";
export const SYSTEM_CONTRACTS_PUBLISH_PERMISSION = "system.contracts.publish";
export const SYSTEM_MODELS_READ_PERMISSION = "system.models.read";
export const SYSTEM_MODELS_SELECT_PERMISSION = "system.models.select";
export const SYSTEM_MODELS_ACTIVATE_PERMISSION = "system.models.activate";
export const SYSTEM_MODELS_ROLLBACK_PERMISSION = "system.models.rollback";
export const SYSTEM_AUDIT_READ_PERMISSION = "system.audit.read";
export const SYSTEM_LOGS_READ_PERMISSION = "system.logs.read";
export const SYSTEM_LOGS_EXPORT_PERMISSION = "system.logs.export";
export const SYSTEM_RECOVERY_GUIDES_READ_PERMISSION = "system.recovery_guides.read";
export const SYSTEM_E2E_READ_PERMISSION = "system.e2e.read";

export function canReadSystemOperationalAssets(permissions: readonly string[] | null | undefined) {
  return Boolean(permissions?.includes(SYSTEM_ASSETS_READ_PERMISSION));
}

export function canCreateSystemAssetVersion(permissions: readonly string[] | null | undefined) {
  return Boolean(permissions?.includes(SYSTEM_ASSETS_CREATE_VERSION_PERMISSION));
}

export function canValidateSystemAsset(permissions: readonly string[] | null | undefined) {
  return Boolean(permissions?.includes(SYSTEM_ASSETS_VALIDATE_PERMISSION));
}

export function canPublishSystemAsset(permissions: readonly string[] | null | undefined) {
  return Boolean(permissions?.includes(SYSTEM_ASSETS_PUBLISH_PERMISSION));
}

export function canReadSystemJobs(permissions: readonly string[] | null | undefined) {
  return Boolean(permissions?.includes(SYSTEM_JOBS_READ_PERMISSION));
}

export function canCreateSystemJob(permissions: readonly string[] | null | undefined) {
  return Boolean(permissions?.includes(SYSTEM_JOBS_CREATE_PERMISSION));
}

export function canCancelSystemJob(permissions: readonly string[] | null | undefined) {
  return Boolean(permissions?.includes(SYSTEM_JOBS_CANCEL_PERMISSION));
}

export function canCreateImpactAnalysis(permissions: readonly string[] | null | undefined) {
  return Boolean(permissions?.includes(SYSTEM_IMPACT_CREATE_PERMISSION));
}

export function canReadSystemImpact(permissions: readonly string[] | null | undefined) { return Boolean(permissions?.includes(SYSTEM_IMPACT_READ_PERMISSION)); }
export function canReadManagedContracts(permissions: readonly string[] | null | undefined) { return Boolean(permissions?.includes(SYSTEM_CONTRACTS_READ_PERMISSION)); }

export function canExecuteSystemRebuild(permissions: readonly string[] | null | undefined) {
  return Boolean(permissions?.includes(SYSTEM_REBUILD_EXECUTE_PERMISSION));
}

export function canCreateManagedContract(permissions: readonly string[] | null | undefined) { return Boolean(permissions?.includes(SYSTEM_CONTRACTS_CREATE_PERMISSION)); }
export function canValidateManagedContract(permissions: readonly string[] | null | undefined) { return Boolean(permissions?.includes(SYSTEM_CONTRACTS_VALIDATE_PERMISSION)); }
export function canPublishManagedContract(permissions: readonly string[] | null | undefined) { return Boolean(permissions?.includes(SYSTEM_CONTRACTS_PUBLISH_PERMISSION)); }
export function canReadSystemModels(permissions: readonly string[] | null | undefined) { return Boolean(permissions?.includes(SYSTEM_MODELS_READ_PERMISSION)); }
export function canSelectSystemModels(permissions: readonly string[] | null | undefined) { return Boolean(permissions?.includes(SYSTEM_MODELS_SELECT_PERMISSION)); }
export function canActivateSystemModels(permissions: readonly string[] | null | undefined) { return Boolean(permissions?.includes(SYSTEM_MODELS_ACTIVATE_PERMISSION)); }
export function canRollbackSystemModels(permissions: readonly string[] | null | undefined) { return Boolean(permissions?.includes(SYSTEM_MODELS_ROLLBACK_PERMISSION)); }
export function canReadSystemAudit(permissions: readonly string[] | null | undefined) { return Boolean(permissions?.includes(SYSTEM_AUDIT_READ_PERMISSION)); }
export function canReadSystemLogs(permissions: readonly string[] | null | undefined) { return Boolean(permissions?.includes(SYSTEM_LOGS_READ_PERMISSION)); }
export function canExportSystemLogs(permissions: readonly string[] | null | undefined) { return Boolean(permissions?.includes(SYSTEM_LOGS_EXPORT_PERMISSION)); }
export function canReadRecoveryGuides(permissions: readonly string[] | null | undefined) { return Boolean(permissions?.includes(SYSTEM_RECOVERY_GUIDES_READ_PERMISSION)); }
export function canReadSystemE2E(permissions: readonly string[] | null | undefined) { return Boolean(permissions?.includes(SYSTEM_E2E_READ_PERMISSION)); }

const SYSTEM_OPERATIONS_READ_PERMISSIONS = [
  SYSTEM_ASSETS_READ_PERMISSION, SYSTEM_JOBS_READ_PERMISSION, SYSTEM_IMPACT_READ_PERMISSION,
  SYSTEM_CONTRACTS_READ_PERMISSION, SYSTEM_MODELS_READ_PERMISSION, SYSTEM_AUDIT_READ_PERMISSION,
  SYSTEM_LOGS_READ_PERMISSION, SYSTEM_E2E_READ_PERMISSION,
] as const;

export function hasAnySystemOperationsPermission(permissions: readonly string[] | null | undefined) {
  return Boolean(permissions?.some((permission) => SYSTEM_OPERATIONS_READ_PERMISSIONS.includes(permission as typeof SYSTEM_OPERATIONS_READ_PERMISSIONS[number])));
}
