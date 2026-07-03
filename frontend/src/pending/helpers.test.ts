import type { Invoice } from "../types";
import { getPendingRowStatus, pendingFileTypeLabel, sortPendingRows } from "./helpers";

function makeInvoice(overrides: Partial<Invoice>): Invoice {
  return {
    id: 1,
    original_filename: "invoice.pdf",
    stored_filename: "invoice.pdf",
    file_path: "/tmp/invoice.pdf",
    mime_type: "application/pdf",
    status: "pending",
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
    extracted_data: {
      supplier_confirmed: true,
      vendor_matched: true,
      vendor_match_confidence: 0.94
    },
    ...overrides
  };
}

function assertEqual<T>(actual: T, expected: T, label: string) {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

const ready = makeInvoice({ id: 1 });
const needsConfirm = makeInvoice({
  id: 2,
  vendor_code: "",
  vendor_name: "",
  extracted_data: { supplier_warning: "missing supplier", vendor_match_confidence: 0.2 }
});
const scanning = makeInvoice({ id: 3, extracted_data: { supplier_stage: "scanning" } });

assertEqual(getPendingRowStatus(ready, new Set()).filter, "ready", "ready invoice status");
assertEqual(getPendingRowStatus(needsConfirm, new Set()).filter, "needs-confirm", "needs-confirm invoice status");
assertEqual(getPendingRowStatus(scanning, new Set()).filter, "recognizing", "scanning invoice status");
assertEqual(getPendingRowStatus(ready, new Set([1])).filter, "recognizing", "active recognition overrides ready");
assertEqual(pendingFileTypeLabel(ready), "PDF", "pdf label");
assertEqual(sortPendingRows([needsConfirm, ready, scanning])[0]?.id, 3, "scanning rows sort first");
