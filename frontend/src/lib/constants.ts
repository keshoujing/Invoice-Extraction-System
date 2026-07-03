import type { PromptFieldConfig, PromptTagExportColumn } from "../types";

export type Tab = "pending" | "review" | "confirmed" | "rules";

export const LLM_VALIDATION_ISSUES_KEY = "_llm_validation_issues";
export const MANUAL_CONFIRMATION_REQUIRED_FIELDS_KEY = "_manual_confirmation_required_fields";
export const MANUAL_CONFIRMATION_REQUIRED_KEY = "_manual_confirmation_required";
export const HITL_MODEL_OUTPUT_KEY = "_hitl_model_output";

export const systemExtractedDataKeys = new Set([
  LLM_VALIDATION_ISSUES_KEY,
  MANUAL_CONFIRMATION_REQUIRED_FIELDS_KEY,
  MANUAL_CONFIRMATION_REQUIRED_KEY,
  HITL_MODEL_OUTPUT_KEY
]);

export const standardFields = [
  ["vendor_code", "Vendor Code"],
  ["vendor_name", "Vendor Name"],
  ["invoice_category", "Invoice Category"],
  ["PO_number", "PO"],
  ["invoice_number", "Invoice Number"],
  ["invoice_date", "Invoice Date"],
  ["total_amount", "Amount"],
  ["unit_price", "Unit Price"],
  ["commodity_amount", "Commodity Amount"],
  ["freight_amount", "Freight"],
  ["tax_amount", "Tax Amount"],
  ["Is_Invoice", "Is Invoice"]
] as const;

export const fieldAliases: Record<string, string[]> = {
  vendor_code: ["vendor_code", "supplier_code", "Vendor Code"],
  vendor_name: ["vendor_name", "Vendor Name"],
  invoice_category: ["invoice_category", "Invoice Category"],
  PO_number: ["PO_number", "po_number", "PO"],
  invoice_number: ["invoice_number", "Invoice Number"],
  invoice_date: ["invoice_date", "Invoice Date"],
  total_amount: ["total_amount", "Amount"]
};

export const systemExportColumns: PromptTagExportColumn[] = [
  { key: "archive_number", label: "Archive Number", enabled: true, source: "scalar", row_mode: "repeat", type: "string" },
  { key: "expense_type", label: "Expense Type", enabled: true, source: "scalar", row_mode: "repeat", type: "string" },
  { key: "vendor_code", label: "Vendor Code", enabled: true, source: "scalar", row_mode: "repeat", type: "string" },
  { key: "vendor_name", label: "Vendor Name", enabled: true, source: "scalar", row_mode: "repeat", type: "string" },
  { key: "po_number", label: "PO", enabled: true, source: "scalar", row_mode: "repeat", type: "string" },
  { key: "invoice_number", label: "Invoice Number", enabled: true, source: "scalar", row_mode: "repeat", type: "string" },
  { key: "invoice_date", label: "Invoice Date", enabled: true, source: "scalar", row_mode: "repeat", type: "string" },
  { key: "total_amount", label: "Amount", enabled: true, source: "scalar", row_mode: "repeat", type: "value" },
  { key: "invoice_category", label: "Invoice Category", enabled: true, source: "scalar", row_mode: "repeat", type: "string" }
];

export const systemExportDedupeKeys = new Set([
  "archive_number",
  "expense_type",
  "vendor_code",
  "supplier_code",
  "vendor_name",
  "po_number",
  "po",
  "customer_po",
  "invoice_number",
  "invoice_date",
  "total_amount",
  "invoice_category"
]);

export const fixedVendorField: PromptFieldConfig = {
  key: "vendor_name",
  type: "string",
  group: "supplier",
  examples: "AIR PRODUCTS"
};

export const fieldGroupOptions = [
  { value: "supplier", label: "Supplier Info" },
  { value: "invoice", label: "Invoice Info" },
  { value: "amount", label: "Amounts" },
  { value: "line_items", label: "Line Items" },
  { value: "other", label: "Other Fields" }
] as const;

export type FieldGroup = typeof fieldGroupOptions[number]["value"];

export const fieldGroupLabels = Object.fromEntries(
  fieldGroupOptions.map((group) => [group.value, group.label])
) as Record<FieldGroup, string>;

export const STORAGE_KEYS = {
  tab: "invoiceArchive.activeTab",
  activeTab: "invoiceArchive.activeTab",
  selectedReviewId: "invoiceArchive.selectedReviewId",
  exportDestinationDir: "invoiceArchive.export.destinationDir",
  exportPrefix: "invoiceArchive.export.prefix",
  exportStartNumber: "invoiceArchive.export.startNumber",
  exportCreateNewFolder: "invoiceArchive.export.createNewFolder",
  exportStatus: "invoiceArchive.export.status"
} as const;

export const expenseTypeOptions = [
  { value: "", label: "Blank" },
  { value: "Non-expense", label: "Non-expense" },
  { value: "Expense", label: "Expense" },
  { value: "CN", label: "CN" }
] as const;
