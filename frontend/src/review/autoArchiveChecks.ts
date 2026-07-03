import type { SupplierAutoArchiveCheck, SupplierAutoArchiveConfig } from "../types";
import { exportLabelForKey } from "../lib/prompt";

export const AUTO_ARCHIVE_FAILED_FIELDS_KEY = "_auto_archive_failed_fields";

export interface AutoArchiveCheckView {
  key: string;
  label: string;
  baseline_value: string;
  tolerance_percent: string;
}

export function autoArchiveChecksForSupplierConfig(config: SupplierAutoArchiveConfig | null): AutoArchiveCheckView[] {
  if (!config) return [];
  const available = new Set(config.available_fields.map((field) => field.toLowerCase()));
  return config.checks
    .filter((check) => check.enabled && available.has(check.field_key.toLowerCase()))
    .map((check) => ({
      key: check.field_key,
      label: exportLabelForKey(check.field_key),
      baseline_value: String(check.baseline_value || ""),
      tolerance_percent: String(check.tolerance_percent || "")
    }));
}

export function failedAutoArchiveFields(data: Record<string, unknown>): Set<string> {
  const raw = data[AUTO_ARCHIVE_FAILED_FIELDS_KEY];
  if (!Array.isArray(raw)) return new Set();
  return new Set(raw.map((item) => String(item || "").trim().toLowerCase()).filter(Boolean));
}

export function upsertSupplierAutoArchiveCheck(
  checks: SupplierAutoArchiveCheck[],
  next: SupplierAutoArchiveCheck
): SupplierAutoArchiveCheck[] {
  const target = next.field_key.trim().toLowerCase();
  const output = checks.filter((check) => check.field_key.trim().toLowerCase() !== target);
  return [...output, next];
}
