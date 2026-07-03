import { useEffect, useMemo, useState } from "react";
import { fileUrl } from "../api";
import {
  pendingDocumentIsInvoice,
  pendingDocumentTypeLabel,
  pendingSupplierConfidence,
  pendingSupplierConfirmed,
  pendingSupplierWarning
} from "../lib/invoice";
import { supplierMatchesQuery } from "../lib/prompt";
import { useDebounce } from "../lib/hooks";
import type { Invoice, Supplier } from "../types";
import { Button } from "../ui/Button";
import { Drawer } from "../ui/Drawer";
import { Field, TextInput } from "../ui/Field";
import { Badge } from "../ui/Badge";
import { pendingWarnings } from "./helpers";

type WarningDrawerProps = {
  invoice: Invoice | null;
  open: boolean;
  suppliers: Supplier[];
  saving: boolean;
  deleting?: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (invoice: Invoice, payload: { vendor_code: string; vendor_name: string; markAsInvoice: boolean }) => Promise<void>;
  onDelete?: (invoice: Invoice) => Promise<boolean | void> | boolean | void;
  onOpenSpecialPrompt?: (invoice: Invoice) => void;
  draftForSupplier: (invoice: Invoice, name: string) => { vendor_code: string; vendor_name: string };
  initialDraftFor: (invoice: Invoice) => { vendor_code: string; vendor_name: string };
};

export function WarningDrawer({
  invoice,
  open,
  suppliers,
  saving,
  deleting = false,
  onOpenChange,
  onSave,
  onDelete,
  onOpenSpecialPrompt,
  draftForSupplier,
  initialDraftFor
}: WarningDrawerProps) {
  const [vendorName, setVendorName] = useState("");
  const [vendorCode, setVendorCode] = useState("");
  const [markAsInvoice, setMarkAsInvoice] = useState(true);
  const debouncedVendorName = useDebounce(vendorName, 250);

  useEffect(() => {
    if (!invoice || !open) return;
    const draft = initialDraftFor(invoice);
    setVendorName(draft.vendor_name);
    setVendorCode(draft.vendor_code);
    setMarkAsInvoice(pendingDocumentIsInvoice(invoice));
  }, [initialDraftFor, invoice, open]);

  const matches = useMemo(() => {
    const query = debouncedVendorName.trim();
    if (!query) return suppliers.slice(0, 6);
    return suppliers.filter((supplier) => supplierMatchesQuery(supplier, query)).slice(0, 6);
  }, [debouncedVendorName, suppliers]);

  if (!invoice) {
    return (
      <Drawer open={open} onOpenChange={onOpenChange} title="Warning Details">
        <p className="text-sm text-ink-500">No pending invoice selected.</p>
      </Drawer>
    );
  }

  const warnings = pendingWarnings(invoice);
  const canSave = markAsInvoice && vendorName.trim() && !saving && !deleting;
  const actionsDisabled = saving || deleting;

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title={invoice.original_filename}
      description="Manually confirm supplier and document type"
      width={480}
      footer={
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            {onOpenSpecialPrompt ? (
              <Button
                variant="ghost"
                disabled={actionsDisabled}
                onClick={() => {
                  onOpenChange(false);
                  onOpenSpecialPrompt(invoice);
                }}
              >
                Open Special Document Rules
              </Button>
            ) : null}
            {onDelete ? (
              <Button
                variant="danger"
                disabled={actionsDisabled}
                onClick={async () => {
                  const deleted = await onDelete(invoice);
                  if (deleted) onOpenChange(false);
                }}
              >
                {deleting ? "Deleting" : "Delete File"}
              </Button>
            ) : null}
          </div>
          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" disabled={actionsDisabled} onClick={() => onOpenChange(false)}>Close</Button>
            <Button
              variant="primary"
              disabled={!canSave}
              onClick={async () => {
                await onSave(invoice, {
                  vendor_code: vendorCode.trim(),
                  vendor_name: vendorName.trim(),
                  markAsInvoice
                });
                onOpenChange(false);
              }}
            >
              {saving ? "Saving" : "Save and Confirm"}
            </Button>
          </div>
        </div>
      }
    >
      <div className="space-y-5">
        <div className="grid gap-2 rounded-card bg-brand-50/55 p-4 text-sm text-ink-700">
          <div className="flex items-center justify-between gap-3">
            <span>Document Type</span>
            <Badge variant={pendingDocumentIsInvoice(invoice) ? "ok" : "warn"}>{pendingDocumentTypeLabel(invoice)}</Badge>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span>Supplier Confidence</span>
            <Badge variant={pendingSupplierConfidence(invoice) >= 0.82 ? "ok" : "warn"}>
              {(pendingSupplierConfidence(invoice) * 100).toFixed(0)}%
            </Badge>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span>Current Status</span>
            <Badge variant={pendingSupplierConfirmed(invoice) ? "ok" : "warn"}>
              {pendingSupplierConfirmed(invoice) ? "Confirmed" : "Needs Confirmation"}
            </Badge>
          </div>
        </div>

        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-ink-900">Warnings</h3>
          {warnings.map((warning) => (
            <p key={warning} className="rounded-soft bg-warn-bg px-3 py-2 text-sm font-medium text-warn-text">
              {warning}
            </p>
          ))}
          {!warnings.length ? <p className="text-sm text-ink-500">{pendingSupplierWarning(invoice) || "No warnings"}</p> : null}
        </div>

        <div className="space-y-3">
          <Field label="Confirmed Supplier Name">
            <TextInput
              value={vendorName}
              placeholder="Enter or choose a supplier from supplier.txt"
              onChange={(event) => {
                const draft = draftForSupplier(invoice, event.target.value);
                setVendorName(draft.vendor_name);
                setVendorCode(draft.vendor_code);
              }}
              list="pending-supplier-suggestions"
            />
          </Field>
          <datalist id="pending-supplier-suggestions">
            {matches.map((supplier) => (
              <option key={supplier.code} value={supplier.name}>{supplier.code}</option>
            ))}
          </datalist>
          <Field label="Vendor Code" hint="Auto-matched">
            <TextInput value={vendorCode} readOnly />
          </Field>
          <label className="flex items-start gap-3 rounded-soft border border-ink-300/15 bg-white px-3 py-3 text-sm font-medium text-ink-700">
            <input
              className="mt-1 accent-brand-600"
              type="checkbox"
              checked={markAsInvoice}
              onChange={(event) => setMarkAsInvoice(event.target.checked)}
            />
            <span>This file is an invoice. Confirm it to add it to the ready list.</span>
          </label>
        </div>

        <div className="overflow-hidden rounded-card border border-ink-300/15 bg-white">
          <iframe className="h-72 w-full" src={fileUrl(invoice.id)} title={invoice.original_filename} />
        </div>
      </div>
    </Drawer>
  );
}
