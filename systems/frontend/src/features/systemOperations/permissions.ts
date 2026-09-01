export const SYSTEM_ASSETS_READ_PERMISSION = "system.assets.read";
export const SYSTEM_ASSETS_CREATE_VERSION_PERMISSION = "system.assets.create_version";
export const SYSTEM_ASSETS_VALIDATE_PERMISSION = "system.assets.validate";
export const SYSTEM_ASSETS_PUBLISH_PERMISSION = "system.assets.publish";

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
