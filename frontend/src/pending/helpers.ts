import type { BadgeVariant } from "../ui/Badge";
import type { Invoice } from "../types";
import {
  pendingDocumentTypeLabel,
  pendingSupplierConfirmed,
  pendingSupplierScanning
} from "../lib/invoice";

export type PendingFilter = "all" | "ready" | "needs-confirm" | "recognizing";

export type PendingRowStatus = {
  filter: Exclude<PendingFilter, "all">;
  label: "Ready" | "Needs Confirmation" | "Recognizing";
  badgeVariant: BadgeVariant;
  isRecognizing: boolean;
};

const pendingPriority: Record<PendingRowStatus["filter"], number> = {
  recognizing: 0,
  "needs-confirm": 1,
  ready: 2
};

export function isJobActive(status?: "queued" | "running" | "completed" | "failed") {
  return status === "queued" || status === "running";
}

export function mergeInvoicesPreservingCurrentOrder(current: Invoice[], incomingRows: Invoice[]) {
  if (!current.length) return incomingRows;
  const incoming = new Map(incomingRows.map((invoice) => [invoice.id, invoice]));
  const existingIds = new Set(current.map((invoice) => invoice.id));
  const next = current
    .map((invoice) => incoming.get(invoice.id))
    .filter((invoice): invoice is Invoice => Boolean(invoice));
  for (const invoice of incomingRows) {
    if (!existingIds.has(invoice.id)) next.push(invoice);
  }
  return next;
}

export function appendPendingInvoices(current: Invoice[], invoices: Invoice[]) {
  if (!invoices.length) return current;
  const incoming = new Map(invoices.map((invoice) => [invoice.id, invoice]));
  const existingIds = new Set(current.map((invoice) => invoice.id));
  const appendAfterUpdate: Invoice[] = [];
  let changed = false;
  const next = current.flatMap((invoice) => {
    const updated = incoming.get(invoice.id);
    if (!updated) return [invoice];
    changed = true;
    if (pendingSupplierScanning(invoice) && !pendingSupplierScanning(updated)) {
      appendAfterUpdate.push(updated);
      return [];
    }
    return [updated];
  });
  next.push(...appendAfterUpdate);
  for (const invoice of invoices) {
    if (!existingIds.has(invoice.id)) {
      next.push(invoice);
      changed = true;
    }
  }
  return changed ? next : current;
}

export function getPendingRowStatus(invoice: Invoice, activeRecognitionIds: Set<number>): PendingRowStatus {
  if (activeRecognitionIds.has(invoice.id) || pendingSupplierScanning(invoice)) {
    return {
      filter: "recognizing",
      label: "Recognizing",
      badgeVariant: "neutral",
      isRecognizing: true
    };
  }
  if (pendingSupplierConfirmed(invoice)) {
    return {
      filter: "ready",
      label: "Ready",
      badgeVariant: "ok",
      isRecognizing: false
    };
  }
  return {
    filter: "needs-confirm",
    label: "Needs Confirmation",
    badgeVariant: "warn",
    isRecognizing: false
  };
}

export function sortPendingRows(rows: Invoice[], activeRecognitionIds = new Set<number>()) {
  return [...rows].sort((left, right) => {
    const leftStatus = getPendingRowStatus(left, activeRecognitionIds);
    const rightStatus = getPendingRowStatus(right, activeRecognitionIds);
    const priority = pendingPriority[leftStatus.filter] - pendingPriority[rightStatus.filter];
    if (priority !== 0) return priority;
    return right.uploaded_at.localeCompare(left.uploaded_at) || right.id - left.id;
  });
}

export function filterPendingRows(rows: Invoice[], filter: PendingFilter, activeRecognitionIds: Set<number>) {
  const sorted = sortPendingRows(rows, activeRecognitionIds);
  if (filter === "all") return sorted;
  return sorted.filter((invoice) => getPendingRowStatus(invoice, activeRecognitionIds).filter === filter);
}

export function pendingFileTypeLabel(invoice: Invoice) {
  const mime = invoice.mime_type || "";
  if (mime.includes("pdf")) return "PDF";
  if (mime.includes("image/")) return mime.split("/")[1]?.toUpperCase() || "IMAGE";
  const match = (invoice.original_filename || invoice.stored_filename || "").match(/\.([^.]+)$/);
  return match?.[1]?.toUpperCase() || "FILE";
}

export function pendingWarnings(invoice: Invoice) {
  const warning = String(invoice.extracted_data?.supplier_warning ?? "").trim();
  const docType = pendingDocumentTypeLabel(invoice);
  const warnings = warning ? [warning] : [];
  if (docType !== "invoice" && docType !== "unknown") {
    warnings.push(`Document type was recognized as ${docType}; it is not an invoice. Please confirm manually`);
  }
  if (!warnings.length && !pendingSupplierConfirmed(invoice)) warnings.push("No reliable supplier was recognized. Please confirm manually");
  return [...new Set(warnings)];
}
