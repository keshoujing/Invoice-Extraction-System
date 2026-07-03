export type InvoiceStatus = "pending" | "recognized" | "failed" | "confirmed";

export interface Invoice {
  id: number;
  original_filename: string;
  stored_filename: string;
  file_path: string;
  mime_type: string;
  status: InvoiceStatus;
  uploaded_at: string;
  recognized_at?: string | null;
  confirmed_at?: string | null;
  updated_at: string;
  error_message?: string | null;
  vendor_code: string;
  vendor_name: string;
  po_number: string;
  invoice_number: string;
  invoice_date: string;
  invoice_date_iso: string;
  total_amount: number;
  expense_type: string;
  invoice_category: string;
  archive_number?: string | null;
  exported_filename?: string | null;
  exported_path?: string | null;
  export_batch_id?: string | null;
  exported_at?: string | null;
  extracted_data: Record<string, unknown>;
}

export interface LlmValidationIssue {
  field: string;
  expected_type: string;
  raw_value?: unknown;
  message: string;
  requires_manual_confirmation: boolean;
}

export interface RecognitionJob {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  total: number;
  processed: number;
  succeeded: number;
  failed_count: number;
  created_at: string;
  updated_at: string;
  error_message?: string | null;
  auto_archived_by_supplier: AutoArchiveSupplierSummary[];
}

export interface ActiveRecognition {
  job: RecognitionJob | null;
  invoice_ids: number[];
}

export interface UploadPreviewJob {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  total: number;
  processed: number;
  succeeded: number;
  failed_count: number;
  created_at: string;
  updated_at: string;
  error_message?: string | null;
  invoices: Invoice[];
}

export type ExportMode = "all" | "day" | "range" | "supplier" | "category";
export type ExportStatus = "unexported" | "exported" | "all";

export interface Supplier {
  code: string;
  name: string;
}

export interface AutoArchiveSupplierSummary {
  vendor_code: string;
  vendor_name: string;
  count: number;
}

export interface SupplierAutoArchiveCheck {
  field_key: string;
  baseline_value: string;
  tolerance_percent: string;
  enabled: boolean;
}

export interface SupplierAutoArchiveConfig {
  vendor_code: string;
  vendor_name: string;
  scheme_name: string;
  available_fields: string[];
  checks: SupplierAutoArchiveCheck[];
}

export interface PromptFieldConfig {
  key: string;
  type: "string" | "value" | "bool" | "array" | "fixed";
  group?: string;
  examples: string;
  value?: string;
  children?: PromptFieldConfig[];
}

export type ExportRowMode = "merge" | "repeat" | "split_even";

export interface PromptTagExportColumn {
  key: string;
  label: string;
  enabled: boolean;
  source: "scalar" | "array_child";
  row_mode: ExportRowMode;
  array_key?: string;
  child_key?: string;
  type?: PromptFieldConfig["type"];
}

export interface PromptTagExportSettings {
  custom: boolean;
  columns: PromptTagExportColumn[];
}

export interface PromptTag {
  tag: string;
  prompt_body: string;
  fields: PromptFieldConfig[];
  export_settings: PromptTagExportSettings;
  is_default: boolean;
  supplier_count: number;
  updated_at: string;
}

export interface Scheme {
  name: string;
  preview_prompt_body: string;
  preview_prompt_enabled: boolean;
  prompt_body: string;
  fields: PromptFieldConfig[];
  export_settings: PromptTagExportSettings;
  is_default: boolean;
  supplier_count: number;
  updated_at: string;
}

export interface SpecialDocumentRule {
  vendor_code: string;
  vendor_name: string;
  prompt_body: string;
  fields: PromptFieldConfig[];
  is_active: boolean;
  updated_at: string;
}

export interface PromptRulesTagItem {
  tag: string;
  prompt_body: string;
  fields: PromptFieldConfig[];
  export_settings: PromptTagExportSettings;
  is_default: boolean;
  updated_at?: string;
}

export interface PromptRulesSupplierMapItem {
  vendor_code: string;
  tag: string;
  vendor_name?: string;
  updated_at?: string;
}

export interface PromptRulesSpecialDocumentRuleItem {
  vendor_code: string;
  vendor_name?: string;
  prompt_body: string;
  fields: PromptFieldConfig[];
  is_active: boolean;
  updated_at?: string;
}

export interface PromptRulesSchemeItem {
  name: string;
  preview_prompt_body?: string;
  preview_prompt_enabled?: boolean;
  prompt_body: string;
  fields: PromptFieldConfig[];
  export_settings: PromptTagExportSettings;
  is_default: boolean;
  updated_at?: string;
}

export interface PromptRulesSupplierSchemeItem {
  vendor_code: string;
  scheme_name: string;
  updated_at?: string;
}

export interface PromptRulesSupplierItem {
  code: string;
  name: string;
  updated_at?: string;
}

export interface PromptRulesAutoArchiveCheckItem {
  vendor_code: string;
  field_key: string;
  baseline_value: string;
  tolerance_percent: string;
  enabled: boolean;
  updated_at?: string;
}

export interface PromptRulesPayload {
  schema: "invoice-archive.prompt-rules";
  version: number;
  exported_at: string;
  suppliers?: PromptRulesSupplierItem[];
  schemes: PromptRulesSchemeItem[];
  supplier_scheme_map: PromptRulesSupplierSchemeItem[];
  auto_archive_checks?: PromptRulesAutoArchiveCheckItem[];
  tags?: PromptRulesTagItem[];
  supplier_tag_map?: PromptRulesSupplierMapItem[];
  special_document_rules?: PromptRulesSpecialDocumentRuleItem[];
}

export interface PromptRulesImportResult {
  suppliers_created: number;
  suppliers_updated: number;
  tags_created: number;
  tags_updated: number;
  supplier_mappings_imported: number;
  supplier_mappings_removed: number;
  auto_archive_checks_imported: number;
  special_document_rules_created: number;
  special_document_rules_updated: number;
  skipped_supplier_codes: string[];
  skipped_mappings: string[];
  stale_conflicts: Array<{
    kind: "tag" | "supplier" | "supplier_mapping" | "special_document_rule" | "scheme" | "supplier_scheme_mapping" | "auto_archive_check";
    key: string;
    import_updated_at: string;
    local_updated_at: string;
  }>;
  stale_conflicts_skipped: number;
}

export interface ExportResult {
  batch_id: string;
  item_count: number;
  destination_dir: string;
  excel_path: string;
  files: Array<{
    invoice_id: string;
    archive_number: string;
    exported_filename: string;
    exported_path: string;
  }>;
}

export interface ExportStats {
  confirmed_count: number;
  exported_count: number;
  unexported_count: number;
}
