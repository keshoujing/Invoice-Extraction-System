import type {
  PromptFieldConfig,
  PromptRulesImportResult,
  PromptRulesPayload,
  PromptTagExportColumn,
  PromptTagExportSettings,
  Supplier
} from "../types";
import {
  FieldGroup,
  fieldGroupOptions,
  fixedVendorField,
  standardFields,
  systemExportColumns,
  systemExportDedupeKeys
} from "./constants";

export function isFieldGroup(value: string): value is FieldGroup {
  return fieldGroupOptions.some((group) => group.value === value);
}

export function inferFieldGroup(key: string, fieldType: PromptFieldConfig["type"] = "string"): FieldGroup {
  const text = String(key || "").trim().toLowerCase();
  const words = new Set(text.split(/[^a-z0-9\u4e00-\u9fff]+/).filter(Boolean));
  const hasAny = (tokens: string[]) => tokens.some((token) => words.has(token) || text.includes(token));
  if (fieldType === "array") return "line_items";
  if (hasAny(["vendor", "supplier", "seller", "customer", "shipper", "Supplier", "\u5ba2\u6237"])) return "supplier";
  if (hasAny(["amount", "total", "subtotal", "tax", "gst", "vat", "fee", "fees", "charge", "charges", "freight", "shipping", "delivery", "surcharge", "fuel", "energy", "discount", "balance", "due", "Amount", "Expense", "Freight", "\u7a0e", "\u5408\u8ba1"])) return "amount";
  if (hasAny(["item", "items", "line", "lines", "detail", "details", "bol", "material", "sku", "qty", "quantity", "weight", "\u8d27\u7269", "\u660e\u7ec6", "\u6750\u6599", "\u91cd\u91cf"])) return "line_items";
  if (hasAny(["invoice", "inv", "po", "order", "date", "category", "type", "memo", "\u53d1\u7968", "\u65e5\u671f", "\u7c7b\u522b"])) return "invoice";
  return "other";
}

export function normalizeFieldGroup(value: string | undefined, key: string, fieldType: PromptFieldConfig["type"]): FieldGroup {
  return value && isFieldGroup(value) ? value : inferFieldGroup(key, fieldType);
}

export function isFixedVendorField(key: string): boolean {
  return String(key || "").trim().toLowerCase() === "vendor_name";
}

export function normalizePromptChildField(field: PromptFieldConfig): PromptFieldConfig {
  const fieldType = field.type === "value" || field.type === "bool" ? field.type : "string";
  return {
    key: String(field.key || "").trim(),
    type: fieldType,
    group: "line_items",
    examples: String(field.examples || "").trim()
  };
}

export function normalizePromptField(field: PromptFieldConfig): PromptFieldConfig {
  if (isFixedVendorField(field.key)) {
    return { ...fixedVendorField };
  }
  const fieldType = field.type === "value" || field.type === "bool" || field.type === "array" || field.type === "fixed" ? field.type : "string";
  const normalized: PromptFieldConfig = {
    key: String(field.key || "").trim(),
    type: fieldType,
    group: normalizeFieldGroup(field.group, field.key, fieldType),
    examples: fieldType === "fixed" ? "" : String(field.examples || "").trim()
  };
  if (fieldType === "fixed") {
    normalized.value = String(field.value || "").trim();
  }
  if (fieldType === "array") {
    normalized.children = (field.children || [])
      .map(normalizePromptChildField)
      .filter((child) => child.key);
  }
  return normalized;
}

export function normalizePromptFieldDraft(field: PromptFieldConfig): PromptFieldConfig {
  if (isFixedVendorField(field.key)) {
    return { ...fixedVendorField };
  }
  const fieldType = field.type === "value" || field.type === "bool" || field.type === "array" || field.type === "fixed" ? field.type : "string";
  const normalized: PromptFieldConfig = {
    key: String(field.key || "").trim(),
    type: fieldType,
    group: normalizeFieldGroup(field.group, field.key, fieldType),
    examples: fieldType === "fixed" ? "" : String(field.examples || "").trim()
  };
  if (fieldType === "fixed") {
    normalized.value = String(field.value || "").trim();
  }
  if (fieldType === "array") {
    normalized.children = (field.children || []).map(normalizePromptChildField);
  }
  return normalized;
}

export function ensureFixedPromptFields(fields: PromptFieldConfig[]): PromptFieldConfig[] {
  const editable = fields
    .map(normalizePromptField)
    .filter((field) => field.key && !isFixedVendorField(field.key));
  return [{ ...fixedVendorField }, ...editable];
}

export function ensureFixedPromptFieldDrafts(fields: PromptFieldConfig[]): PromptFieldConfig[] {
  const editable = fields
    .map(normalizePromptFieldDraft)
    .filter((field) => !isFixedVendorField(field.key));
  return [{ ...fixedVendorField }, ...editable];
}

export function emptyPromptField(): PromptFieldConfig {
  return { key: "", type: "string", group: "other", examples: "" };
}

export function emptyPromptChildField(): PromptFieldConfig {
  return { key: "", type: "string", group: "line_items", examples: "" };
}

export function exportLabelForKey(key: string): string {
  const match = standardFields.find(([fieldKey]) => fieldKey.toLowerCase() === key.toLowerCase());
  if (match) return match[1];
  const systemMatch = systemExportColumns.find((column) => column.key.toLowerCase() === key.toLowerCase());
  return systemMatch?.label || key;
}

export function normalizeExportColumn(column: PromptTagExportColumn): PromptTagExportColumn {
  const source = column.source === "array_child" ? "array_child" : "scalar";
  const rowMode = column.row_mode === "repeat" || column.row_mode === "split_even" || column.row_mode === "merge"
    ? column.row_mode
    : "repeat";
  const key = String(column.key || "").trim();
  const arrayKey = String(column.array_key || "").trim();
  const childKey = String(column.child_key || "").trim();
  return {
    key,
    label: String(column.label || "").trim() || exportLabelForKey(childKey || key),
    enabled: column.enabled !== false,
    source,
    row_mode: source === "array_child" ? "repeat" : rowMode,
    array_key: source === "array_child" ? arrayKey : "",
    child_key: source === "array_child" ? childKey : "",
    type: column.type || "string"
  };
}

export function defaultExportColumnsForFields(fields: PromptFieldConfig[]): PromptTagExportColumn[] {
  const columns = systemExportColumns.map((column) => ({ ...column }));
  const seen = new Set(columns.map((column) => column.key.toLowerCase()));
  ensureFixedPromptFields(fields).forEach((field) => {
    const key = String(field.key || "").trim();
    if (!key) return;
    if (field.type === "array") {
      (field.children || []).forEach((child) => {
        const childKey = String(child.key || "").trim();
        if (!childKey) return;
        const exportKey = `${key}.${childKey}`;
        if (seen.has(exportKey.toLowerCase())) return;
        seen.add(exportKey.toLowerCase());
        columns.push({
          key: exportKey,
          label: exportLabelForKey(childKey),
          enabled: true,
          source: "array_child",
          row_mode: "repeat",
          array_key: key,
          child_key: childKey,
          type: child.type
        });
      });
      return;
    }
    if (systemExportDedupeKeys.has(key.toLowerCase())) return;
    if (seen.has(key.toLowerCase())) return;
    seen.add(key.toLowerCase());
    columns.push({
      key,
      label: exportLabelForKey(key),
      enabled: true,
      source: "scalar",
      row_mode: "repeat",
      type: field.type
    });
  });
  return columns;
}

export function exportColumnsForFields(
  fields: PromptFieldConfig[],
  settings?: PromptTagExportSettings | null
): PromptTagExportColumn[] {
  const defaultColumns = defaultExportColumnsForFields(fields).map(normalizeExportColumn);
  if (!settings?.custom) return defaultColumns;

  const customColumns = (settings.columns || [])
    .map(normalizeExportColumn)
    .filter((column) => column.key);
  const seen = new Set(customColumns.map((column) => column.key.toLowerCase()));
  defaultColumns.forEach((column) => {
    const key = column.key.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    customColumns.push(column);
  });
  return customColumns;
}

export function normalizeExportSettings(settings?: PromptTagExportSettings | null): PromptTagExportSettings {
  return {
    custom: Boolean(settings?.custom),
    columns: (settings?.columns || [])
      .map(normalizeExportColumn)
      .filter((column) => column.key)
  };
}

export function exportSettingsForSave(settings: PromptTagExportSettings): PromptTagExportSettings {
  const normalized = normalizeExportSettings(settings);
  return normalized.custom ? normalized : { custom: false, columns: [] };
}

export function promptTagEditorSignature(
  tagName: string,
  promptBody: string,
  fields: PromptFieldConfig[],
  exportSettings?: PromptTagExportSettings | null
): string {
  return JSON.stringify({
    tag: tagName.trim(),
    prompt_body: promptBody,
    fields: ensureFixedPromptFieldDrafts(fields),
    export_settings: exportSettingsForSave(normalizeExportSettings(exportSettings))
  });
}

export function promptRulesDownloadName(payload: PromptRulesPayload): string {
  const datePart = String(payload.exported_at || new Date().toISOString()).slice(0, 10) || "rules";
  return `recognition-rules-${datePart}.json`;
}

export function promptRulesImportNotice(result: PromptRulesImportResult): string {
  const suppliersChanged = (result.suppliers_created || 0) + (result.suppliers_updated || 0);
  const specialChanged = (result.special_document_rules_created || 0) + (result.special_document_rules_updated || 0);
  const parts = [`Created ${result.tags_created}`, `Updated ${result.tags_updated}`, `supplier mappings ${result.supplier_mappings_imported}`];
  if (suppliersChanged) parts.push(`Supplier ${suppliersChanged}`);
  if (result.auto_archive_checks_imported) parts.push(`auto-archive ${result.auto_archive_checks_imported}`);
  if (specialChanged) parts.push(`special documents ${specialChanged}`);
  const skippedCount = result.skipped_supplier_codes.length + result.skipped_mappings.length;
  if (skippedCount) parts.push(`skipped ${skippedCount}`);
  if (result.stale_conflicts_skipped) parts.push(`stale configs ${result.stale_conflicts_skipped}`);
  return `Rules import complete: ${parts.join(", ")}`;
}

export function normalizeSupplierInput(value: string): string {
  return value.normalize("NFKC").trim().replace(/\s+/g, " ").toLowerCase();
}

export function supplierMatchesQuery(supplier: Supplier, query: string): boolean {
  const needle = normalizeSupplierInput(query);
  if (!needle) return true;
  return normalizeSupplierInput(supplier.code).includes(needle) || normalizeSupplierInput(supplier.name).includes(needle);
}

export function fieldPathId(path: number[]): string {
  return path.join(".");
}

export function fieldPathFromId(id: string): number[] {
  return id.split(".").map((part) => Number(part)).filter((part) => Number.isFinite(part));
}

export function getFieldAtPath(fields: PromptFieldConfig[], path: number[]): PromptFieldConfig | undefined {
  if (path.length === 1) return fields[path[0]];
  return fields[path[0]]?.children?.[path[1]];
}

export function updateFieldAtPath(
  fields: PromptFieldConfig[],
  path: number[],
  updater: (field: PromptFieldConfig) => PromptFieldConfig
): PromptFieldConfig[] {
  return fields.map((field, index) => {
    if (index !== path[0]) return field;
    if (path.length === 1) return updater(field);
    const children = field.children || [];
    return {
      ...field,
      children: children.map((child, childIndex) => (childIndex === path[1] ? updater(child) : child))
    };
  });
}

export function removeFieldAtPath(fields: PromptFieldConfig[], path: number[]): PromptFieldConfig[] {
  if (path.length === 1) {
    return ensureFixedPromptFields(fields.filter((_, index) => index !== path[0]));
  }
  return fields.map((field, index) => {
    if (index !== path[0]) return field;
    return {
      ...field,
      children: (field.children || []).filter((_, childIndex) => childIndex !== path[1])
    };
  });
}

export function flattenPromptFields(fields: PromptFieldConfig[]): Array<{
  field: PromptFieldConfig;
  path: number[];
  depth: number;
}> {
  return fields.flatMap((field, index) => {
    const parent = { field, path: [index], depth: 0 };
    const children = field.type === "array"
      ? (field.children || []).map((child, childIndex) => ({
        field: child,
        path: [index, childIndex],
        depth: 1
      }))
      : [];
    return [parent, ...children];
  });
}

export function parseFieldExamples(value: string): string[] {
  const text = String(value || "").trim();
  if (!text) return [];
  const parts = text.includes("\n") ? text.split(/\r?\n/) : text.split(",");
  return parts.map((item) => item.trim()).filter(Boolean);
}

export function serializeFieldExamples(examples: string[]): string {
  return examples.map((item) => item.trim()).filter(Boolean).join("\n");
}
