import type { Invoice, PromptFieldConfig } from "../types";
import {
  LLM_VALIDATION_ISSUES_KEY,
  MANUAL_CONFIRMATION_REQUIRED_FIELDS_KEY,
  MANUAL_CONFIRMATION_REQUIRED_KEY,
  systemExtractedDataKeys
} from "./constants";

const FALLBACK_SUPPLIER_THRESHOLD = 0.82;

export type LlmValidationIssue = {
  field: string;
  expected_type: string;
  raw_value?: unknown;
  message: string;
  requires_manual_confirmation: boolean;
};

export function boolFromUnknown(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  return String(value ?? "").trim().toLowerCase() === "true";
}

export function isSystemExtractedDataKey(key: string): boolean {
  return systemExtractedDataKeys.has(key);
}

export function llmValidationIssues(data: Record<string, unknown>): LlmValidationIssue[] {
  const raw = data[LLM_VALIDATION_ISSUES_KEY];
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    .map((item) => ({
      field: String(item.field || "").trim(),
      expected_type: String(item.expected_type || "").trim(),
      raw_value: item.raw_value,
      message: String(item.message || "").trim(),
      requires_manual_confirmation: boolFromUnknown(item.requires_manual_confirmation)
    }))
    .filter((item) => item.field);
}

export function manualConfirmationFields(data: Record<string, unknown>): string[] {
  const raw = data[MANUAL_CONFIRMATION_REQUIRED_FIELDS_KEY];
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const fields: string[] = [];
  raw.forEach((item) => {
    const field = String(item || "").trim();
    if (!field || seen.has(field)) return;
    seen.add(field);
    fields.push(field);
  });
  return fields;
}

export function clearManualConfirmationForField(data: Record<string, unknown>, key: string): Record<string, unknown> {
  const fields = manualConfirmationFields(data).filter((field) => field !== key);
  const issues = llmValidationIssues(data).filter((issue) => issue.field !== key);
  return {
    ...data,
    [MANUAL_CONFIRMATION_REQUIRED_FIELDS_KEY]: fields,
    [LLM_VALIDATION_ISSUES_KEY]: issues,
    [MANUAL_CONFIRMATION_REQUIRED_KEY]: fields.length > 0
  };
}

export function pendingDocumentType(invoice: Invoice): string {
  const raw = String(invoice.extracted_data?.document_type ?? "").trim().toLowerCase();
  if (!raw) return "unknown";
  return raw.replace(/[\s-]+/g, "_");
}

export function pendingDocumentTypeLabel(invoice: Invoice): string {
  const docType = pendingDocumentType(invoice);
  const labels: Record<string, string> = {
    invoice: "invoice",
    statement: "statement",
    purchase_order: "PO",
    po: "PO",
    remittance: "remittance",
    receipt: "receipt",
    credit_memo: "credit memo",
    special_document: "special document",
    other: "other",
    unknown: "unknown"
  };
  return labels[docType] || docType || "unknown";
}

export function pendingDocumentIsInvoice(invoice: Invoice): boolean {
  const data = invoice.extracted_data || {};
  if (Object.prototype.hasOwnProperty.call(data, "document_is_invoice")) {
    return boolFromUnknown(data.document_is_invoice);
  }
  if (Object.prototype.hasOwnProperty.call(data, "Is_Invoice")) {
    return boolFromUnknown(data.Is_Invoice);
  }
  const docType = pendingDocumentType(invoice);
  if (docType === "unknown") return true;
  return docType === "invoice";
}

export function pendingSupplierConfirmed(invoice: Invoice): boolean {
  if (!pendingDocumentIsInvoice(invoice)) return false;
  const data = invoice.extracted_data || {};
  if (boolFromUnknown(data.supplier_confirmed)) return true;
  if (Object.prototype.hasOwnProperty.call(data, "supplier_needs_confirmation")) {
    return !boolFromUnknown(data.supplier_needs_confirmation);
  }
  const code = String(invoice.vendor_code || data.vendor_code || "").trim();
  const name = String(invoice.vendor_name || data.vendor_name || "").trim();
  const matched = boolFromUnknown(data.vendor_matched);
  const confidence = pendingSupplierConfidence(invoice);
  return Boolean(code && name && matched && confidence >= FALLBACK_SUPPLIER_THRESHOLD);
}

export function pendingSupplierScanning(invoice: Invoice): boolean {
  return String(invoice.extracted_data?.supplier_stage ?? "").trim().toLowerCase() === "scanning";
}

export function pendingSupplierRetry(invoice: Invoice): { attempt: number; max: number } | null {
  const data = invoice.extracted_data || {};
  const attempt = Math.floor(Number(data.supplier_retry_attempt ?? 0));
  const max = Math.floor(Number(data.supplier_retry_max ?? 0));
  if (!Number.isFinite(attempt) || !Number.isFinite(max) || attempt < 1 || max < 1) return null;
  return { attempt, max };
}

export function pendingSupplierConfidence(invoice: Invoice): number {
  const raw = invoice.extracted_data?.vendor_match_confidence;
  const value = Number(raw ?? 0);
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

export function pendingSupplierWarning(invoice: Invoice): string {
  if (!pendingDocumentIsInvoice(invoice)) {
    const warning = String(invoice.extracted_data?.supplier_warning ?? "").trim();
    if (warning) return warning;
    return `Document type was recognized as ${pendingDocumentTypeLabel(invoice)}; it is not an invoice. Please confirm manually`;
  }
  const warning = String(invoice.extracted_data?.supplier_warning ?? "").trim();
  if (warning) return warning;
  if (pendingSupplierConfirmed(invoice)) return "";
  return "No reliable supplier was recognized. Please confirm manually";
}

export function isImage(invoice?: Invoice | null): boolean {
  return Boolean(invoice?.mime_type.startsWith("image/"));
}

export function extensionForInvoice(invoice: Invoice): string {
  const name = invoice.file_path || invoice.original_filename || invoice.stored_filename;
  return name.match(/(\.[^./\\]+)$/)?.[1] || ".pdf";
}

export function inferFieldTypeFromValue(value: unknown): PromptFieldConfig["type"] {
  if (typeof value === "number") return "value";
  if (typeof value === "boolean") return "bool";
  return "string";
}

export function arrayRowsFromValue(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item));
}

export function childKeysForArrayField(rows: Record<string, unknown>[], field?: PromptFieldConfig): string[] {
  const keys: string[] = [];
  const seen = new Set<string>();
  const addKey = (key: string) => {
    const clean = String(key || "").trim();
    if (!clean || seen.has(clean)) return;
    seen.add(clean);
    keys.push(clean);
  };
  (field?.children || []).forEach((child) => addKey(child.key));
  rows.slice(0, 8).forEach((row) => Object.keys(row).forEach(addKey));
  return keys;
}
