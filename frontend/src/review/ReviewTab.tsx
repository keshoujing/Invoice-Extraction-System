import { useCallback, useEffect, useMemo, useState } from "react";
import {
  confirmInvoice,
  deleteInvoice,
  getSupplierAutoArchiveConfig,
  listInvoices,
  listSchemes,
  listSuppliers,
  retryInvoice,
  updateSupplierAutoArchiveConfig
} from "../api";
import { STORAGE_KEYS } from "../lib/constants";
import { normalizeSupplierInput } from "../lib/prompt";
import { SpinnerPanel } from "../ui/Spinner";
import { useToast } from "../shell/ToastHost";
import { ReviewForm } from "./ReviewForm";
import { ReviewList } from "./ReviewList";
import { ReviewPreview } from "./ReviewPreview";
import { upsertSupplierAutoArchiveCheck } from "./autoArchiveChecks";
import { useReviewDraft } from "./useReviewDraft";
import type { Invoice, PromptFieldConfig, PromptTag, Scheme, Supplier, SupplierAutoArchiveCheck, SupplierAutoArchiveConfig } from "../types";

function storedReviewId(): number | null {
  const value = window.localStorage.getItem(STORAGE_KEYS.selectedReviewId);
  const id = Number(value);
  return Number.isFinite(id) && id > 0 ? id : null;
}

function mergeInvoicesPreservingCurrentOrder(current: Invoice[], incomingRows: Invoice[]) {
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

export default function ReviewTab() {
  const toast = useToast();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [schemes, setSchemes] = useState<Scheme[]>([]);
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<number | null>(() => storedReviewId());
  const [loading, setLoading] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [autoArchiveConfig, setAutoArchiveConfig] = useState<SupplierAutoArchiveConfig | null>(null);
  const [deletingInvoiceId, setDeletingInvoiceId] = useState<number | null>(null);
  const [retryingInvoiceId, setRetryingInvoiceId] = useState<number | null>(null);

  const successful = useMemo(() => invoices.filter((invoice) => invoice.status === "recognized"), [invoices]);
  const failed = useMemo(() => invoices.filter((invoice) => invoice.status === "failed"), [invoices]);
  const selectedInvoice = useMemo(
    () => invoices.find((invoice) => invoice.id === selectedInvoiceId) || null,
    [invoices, selectedInvoiceId]
  );

  const {
    draft,
    updateField,
    updateFields,
    updateExpenseType,
    replaceArrayField,
    reset,
    save,
    isDirty,
    isSaving
  } = useReviewDraft(selectedInvoice, toast.error);

  const applyReviewRows = useCallback((reviewRows: Invoice[]) => {
    setInvoices((current) => mergeInvoicesPreservingCurrentOrder(current, reviewRows));
    setSelectedInvoiceId((currentId) => {
      if (currentId && reviewRows.some((invoice) => invoice.id === currentId)) return currentId;
      return reviewRows.find((invoice) => invoice.status === "recognized")?.id || reviewRows[0]?.id || null;
    });
  }, []);

  const refreshInvoices = useCallback(async () => {
    const reviewRows = await listInvoices({ status: "review" });
    applyReviewRows(reviewRows);
  }, [applyReviewRows]);

  const refresh = useCallback(async () => {
    const [reviewRows, supplierRows, schemeRows] = await Promise.all([
      listInvoices({ status: "review" }),
      listSuppliers(),
      listSchemes()
    ]);
    applyReviewRows(reviewRows);
    setSuppliers(supplierRows);
    setSchemes(schemeRows);
  }, [applyReviewRows]);

  useEffect(() => {
    refresh()
      .catch((err) => toast.error(err instanceof Error ? err.message : "Failed to load review list"))
      .finally(() => setLoading(false));
  }, [refresh, toast]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      refreshInvoices().catch(() => {
        // Keep polling quiet; the initial load and direct actions still surface errors.
      });
    }, 2500);
    return () => window.clearInterval(timer);
  }, [refreshInvoices]);

  useEffect(() => {
    if (selectedInvoiceId) {
      window.localStorage.setItem(STORAGE_KEYS.selectedReviewId, String(selectedInvoiceId));
    } else {
      window.localStorage.removeItem(STORAGE_KEYS.selectedReviewId);
    }
  }, [selectedInvoiceId]);

  const selectedPromptTag = useMemo(() => {
    const tagName = String(draft.data.prompt_tag || selectedInvoice?.extracted_data?.prompt_tag || "").trim();
    if (!tagName) return null;
    const scheme = schemes.find((item) => item.name === tagName);
    return scheme ? { ...scheme, tag: scheme.name } satisfies PromptTag : null;
  }, [draft.data.prompt_tag, schemes, selectedInvoice]);

  const suppliersByCode = useMemo(
    () => new Map(suppliers.map((supplier) => [normalizeSupplierInput(supplier.code), supplier])),
    [suppliers]
  );
  const suppliersByName = useMemo(
    () => new Map(suppliers.map((supplier) => [normalizeSupplierInput(supplier.name), supplier])),
    [suppliers]
  );

  useEffect(() => {
    const code = String(draft.data.vendor_code || selectedInvoice?.vendor_code || selectedInvoice?.extracted_data?.vendor_code || "").trim();
    if (!code) {
      setAutoArchiveConfig(null);
      return;
    }
    let cancelled = false;
    getSupplierAutoArchiveConfig(code)
      .then((config) => {
        if (!cancelled) setAutoArchiveConfig(config);
      })
      .catch(() => {
        if (!cancelled) setAutoArchiveConfig(null);
      });
    return () => {
      cancelled = true;
    };
  }, [draft.data.vendor_code, selectedInvoice]);

  function handleSelect(invoice: Invoice) {
    setSelectedInvoiceId(invoice.id);
    if (invoice.status === "failed") toast.info("Enter invoice details manually on the right");
  }

  function handleSupplierCommit(key: "vendor_code" | "vendor_name", value: string) {
    if (key === "vendor_code") {
      const supplier = suppliersByCode.get(normalizeSupplierInput(value));
      updateFields([
        { key: "vendor_code", value },
        ...(supplier ? [{ key: "vendor_name", value: supplier.name }] : [])
      ]);
      return;
    }
    const supplier = suppliersByName.get(normalizeSupplierInput(value));
    updateFields([
      { key: "vendor_name", value },
      ...(!value.trim() ? [{ key: "vendor_code", value: "" }] : []),
      ...(supplier ? [{ key: "vendor_code", value: supplier.code }] : [])
    ]);
  }

  async function handleConfirm() {
    if (!selectedInvoice) return;
    setConfirming(true);
    try {
      await save();
      await confirmInvoice(selectedInvoice.id);
      toast.success(selectedInvoice.status === "failed" ? "Manually entered invoice confirmed and archived" : "Invoice confirmed and archived");
      setSelectedInvoiceId(null);
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Confirmation failed");
    } finally {
      setConfirming(false);
    }
  }

  async function handleRetry(invoiceId: number) {
    setRetryingInvoiceId(invoiceId);
    try {
      await retryInvoice(invoiceId);
      toast.info("Recognition resubmitted");
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Retry failed");
    } finally {
      setRetryingInvoiceId(null);
    }
  }

  async function handleDelete(invoice: Invoice) {
    const confirmed = window.confirm(`Delete ${invoice.original_filename}？`);
    if (!confirmed) return;
    setDeletingInvoiceId(invoice.id);
    try {
      await deleteInvoice(invoice.id);
      if (selectedInvoiceId === invoice.id) setSelectedInvoiceId(null);
      toast.success("Invoice deleted");
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeletingInvoiceId(null);
    }
  }

  async function handleAutoArchiveCheckSave(check: SupplierAutoArchiveCheck) {
    if (!autoArchiveConfig) return;
    try {
      const checks = upsertSupplierAutoArchiveCheck(autoArchiveConfig.checks, check);
      const updated = await updateSupplierAutoArchiveConfig(autoArchiveConfig.vendor_code, checks);
      setAutoArchiveConfig(updated);
      toast.success("Auto-archive checks updated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save auto-archive checks");
    }
  }

  if (loading) return <SpinnerPanel label="Loading review invoices" />;

  return (
    <section className="h-[calc(100vh-112px)] min-h-0 overflow-hidden">
      <div className="grid h-full min-h-0 grid-cols-[280px_minmax(0,1fr)_320px] gap-3">
        <ReviewList
          successful={successful}
          failed={failed}
          selectedInvoiceId={selectedInvoiceId}
          deletingInvoiceId={deletingInvoiceId}
          retryingInvoiceId={retryingInvoiceId}
          onSelect={handleSelect}
          onRetry={(invoiceId) => void handleRetry(invoiceId)}
          onDelete={(invoice) => void handleDelete(invoice)}
        />
        <ReviewPreview invoice={selectedInvoice} />
        <ReviewForm
          invoice={selectedInvoice}
          draft={draft}
          suppliers={suppliers}
          promptTag={selectedPromptTag}
          autoArchiveConfig={autoArchiveConfig}
          disabled={confirming}
          isDirty={isDirty}
          isSaving={isSaving}
          onFieldCommit={(key: string, value: string, fieldType?: PromptFieldConfig["type"]) => updateField(key, value, fieldType)}
          onSupplierCommit={handleSupplierCommit}
          onExpenseTypeChange={updateExpenseType}
          onArrayChange={replaceArrayField}
          onAutoArchiveCheckSave={(check) => void handleAutoArchiveCheckSave(check)}
          onCancel={() => {
            reset();
            setSelectedInvoiceId(null);
          }}
          onConfirm={() => void handleConfirm()}
        />
      </div>
    </section>
  );
}
