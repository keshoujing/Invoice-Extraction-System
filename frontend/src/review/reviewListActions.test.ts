import type { Invoice } from "../types";
import { reviewListActionsForInvoice } from "./reviewListActions";

function makeInvoice(overrides: Partial<Invoice>): Invoice {
  return {
    id: 1,
    original_filename: "invoice.pdf",
    stored_filename: "invoice.pdf",
    file_path: "/tmp/invoice.pdf",
    mime_type: "application/pdf",
    status: "recognized",
    uploaded_at: "2026-05-01T00:00:00Z",
    updated_at: "2026-05-01T00:00:00Z",
    vendor_code: "V001",
    vendor_name: "Acme",
    po_number: "",
    invoice_number: "",
    invoice_date: "",
    invoice_date_iso: "",
    total_amount: 0,
    expense_type: "",
    invoice_category: "",
    extracted_data: {},
    ...overrides
  };
}

function assertIncludes<T>(actual: T[], expected: T, label: string) {
  if (!actual.includes(expected)) {
    throw new Error(`${label}: expected ${String(expected)} in ${actual.map(String).join(", ")}`);
  }
}

function assertNotIncludes<T>(actual: T[], expected: T, label: string) {
  if (actual.includes(expected)) {
    throw new Error(`${label}: did not expect ${String(expected)} in ${actual.map(String).join(", ")}`);
  }
}

assertIncludes(reviewListActionsForInvoice(makeInvoice({ status: "recognized" })), "delete", "recognized rows can be deleted");
assertIncludes(reviewListActionsForInvoice(makeInvoice({ status: "failed" })), "delete", "failed rows can be deleted");
assertIncludes(reviewListActionsForInvoice(makeInvoice({ status: "failed" })), "retry", "failed rows can be retried");
assertNotIncludes(reviewListActionsForInvoice(makeInvoice({ status: "recognized" })), "retry", "recognized rows are not retried from review list");
