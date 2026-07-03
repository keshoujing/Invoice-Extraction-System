import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  confirmPendingSupplier,
  deleteInvoice,
  getActiveRecognition,
  getActiveUploadPreview,
  getJob,
  getUploadPreviewJob,
  listInvoices,
  listSuppliers,
  listSupplierSchemeMap,
  retryInvoice,
  retrySupplierPreview,
  saveExtractedData,
  startRecognition as startRecognitionJob,
  uploadInvoices
} from "../api";
import {
  pendingDocumentIsInvoice,
  pendingSupplierConfirmed,
  pendingSupplierWarning
} from "../lib/invoice";
import { normalizeSupplierInput } from "../lib/prompt";
import type { AutoArchiveSupplierSummary, Invoice, RecognitionJob, Supplier, UploadPreviewJob } from "../types";
import {
  appendPendingInvoices,
  isJobActive,
  mergeInvoicesPreservingCurrentOrder
} from "./helpers";

export type PendingUploadSummary = {
  uploaded: number;
  recognized: number;
  scanning: boolean;
};

type ToastApi = {
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
  upsert: (id: string, tone: "success" | "error" | "info", message: string) => void;
};

function supplierDraftFor(invoice: Invoice) {
  return {
    vendor_code: String(invoice.extracted_data?.vendor_code ?? invoice.vendor_code ?? "").trim(),
    vendor_name: String(invoice.extracted_data?.vendor_name ?? invoice.vendor_name ?? "").trim()
  };
}

function autoArchiveCountMap(items: AutoArchiveSupplierSummary[] = []): Map<string, AutoArchiveSupplierSummary> {
  const entries: Array<[string, AutoArchiveSupplierSummary]> = [];
  items.forEach((item) => {
    const key = item.vendor_code || item.vendor_name;
    if (key) entries.push([key, item]);
  });
  return new Map(entries);
}

function notifyAutoArchived(previousJob: RecognitionJob, nextJob: RecognitionJob, toast: ToastApi) {
  const previous = autoArchiveCountMap(previousJob.auto_archived_by_supplier);
  const next = autoArchiveCountMap(nextJob.auto_archived_by_supplier);
  next.forEach((item, key) => {
    const previousCount = previous.get(key)?.count || 0;
    if (item.count <= previousCount) return;
    const label = item.vendor_name || item.vendor_code || "Supplier";
    toast.upsert(`auto-archive-${key}`, "info", `${label} auto-archived ${item.count} invoices`);
  });
}

export function usePendingData(toast: ToastApi) {
  const [rows, setRows] = useState<Invoice[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [promptTagBySupplierCode, setPromptTagBySupplierCode] = useState<Record<string, string>>({});
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [recognitionJob, setRecognitionJob] = useState<RecognitionJob | null>(null);
  const [uploadJob, setUploadJob] = useState<UploadPreviewJob | null>(null);
  const [activeRecognitionIds, setActiveRecognitionIds] = useState<Set<number>>(new Set());
  const [isLoading, setIsLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [updatingSupplierId, setUpdatingSupplierId] = useState<number | null>(null);
  const [previewRetryingId, setPreviewRetryingId] = useState<number | null>(null);
  const [uploadSummary, setUploadSummary] = useState<PendingUploadSummary | null>(null);
  const [mutationVersion, setMutationVersion] = useState(0);
  const refreshInFlightRef = useRef(false);
  const uploadSummaryTimerRef = useRef<number | null>(null);
  const toastRef = useRef(toast);

  useEffect(() => {
    toastRef.current = toast;
  }, [toast]);

  const suppliersByName = useMemo(() => (
    new Map(suppliers.map((supplier) => [normalizeSupplierInput(supplier.name), supplier]))
  ), [suppliers]);

  const refresh = useCallback(async () => {
    const pendingRows = await listInvoices({ status: "pending" });
    startTransition(() => {
      setRows((current) => mergeInvoicesPreservingCurrentOrder(current, pendingRows));
      setSelectedIds((ids) => new Set([...ids].filter((id) => pendingRows.some((item) => item.id === id))));
      setIsLoading(false);
    });
  }, []);

  useEffect(() => {
    Promise.all([
      refresh(),
      listSuppliers(),
      listSupplierSchemeMap(),
      getActiveRecognition(),
      getActiveUploadPreview()
    ])
      .then(([, supplierRows, supplierMap, activeRecognition, activeUpload]) => {
        startTransition(() => {
          setSuppliers(supplierRows);
          setPromptTagBySupplierCode(supplierMap);
          // Restore in-progress job state from the server so that switching tabs
          // (which unmounts this hook) or reloading the page keeps the recognition
          // spinners + checkbox lock and resumes polling instead of losing them.
          if (activeRecognition.invoice_ids.length) {
            setActiveRecognitionIds(new Set(activeRecognition.invoice_ids));
          }
          if (activeRecognition.job && isJobActive(activeRecognition.job.status)) {
            setRecognitionJob(activeRecognition.job);
          }
          if (activeUpload && isJobActive(activeUpload.status)) {
            setUploadJob(activeUpload);
          }
        });
      })
      .catch((error) => {
        setIsLoading(false);
        toastRef.current.error(error instanceof Error ? error.message : "Failed to load pending invoices");
      });
  }, [refresh]);

  useEffect(() => {
    return () => {
      if (uploadSummaryTimerRef.current !== null) window.clearTimeout(uploadSummaryTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (!recognitionJob || !isJobActive(recognitionJob.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const previousJob = recognitionJob;
        const nextJob = await getJob(recognitionJob.id);
        startTransition(() => setRecognitionJob(nextJob));
        notifyAutoArchived(previousJob, nextJob, toastRef.current);
        const progressed = nextJob.processed !== previousJob.processed;
        const justFinished = isJobActive(previousJob.status) && !isJobActive(nextJob.status);
        if ((progressed || justFinished) && !refreshInFlightRef.current) {
          refreshInFlightRef.current = true;
          await refresh();
          refreshInFlightRef.current = false;
        }
        if (justFinished) {
          toastRef.current.success(`Recognition complete: ${nextJob.succeeded} succeeded, ${nextJob.failed_count}`);
          startTransition(() => setActiveRecognitionIds(new Set()));
        }
      } catch (error) {
        refreshInFlightRef.current = false;
        toastRef.current.error(error instanceof Error ? error.message : "Failed to read job status");
      }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [recognitionJob, refresh]);

  useEffect(() => {
    if (!uploadJob || !isJobActive(uploadJob.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const previousJob = uploadJob;
        const nextJob = await getUploadPreviewJob(uploadJob.id);
        startTransition(() => {
          setRows((current) => appendPendingInvoices(current, nextJob.invoices));
          setUploadJob(nextJob);
          setUploadSummary({ uploaded: nextJob.total, recognized: nextJob.processed, scanning: isJobActive(nextJob.status) });
        });
        // Converge the pending list to canonical server state on every step, like the
        // recognition poll does. Without this the row keeps its stale scanning state
        // until a tab switch forces a full reload.
        const progressed = nextJob.processed !== previousJob.processed;
        const justFinished = isJobActive(previousJob.status) && !isJobActive(nextJob.status);
        if ((progressed || justFinished) && !refreshInFlightRef.current) {
          refreshInFlightRef.current = true;
          await refresh();
          refreshInFlightRef.current = false;
        }
        if (justFinished) {
          toastRef.current.success(`Supplier preview complete: ${nextJob.processed} processed, ${nextJob.failed_count}`);
          uploadSummaryTimerRef.current = window.setTimeout(() => setUploadSummary(null), 4200);
        }
      } catch (error) {
        refreshInFlightRef.current = false;
        toastRef.current.error(error instanceof Error ? error.message : "Failed to read upload preview status");
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [uploadJob, refresh]);

  const uploadFiles = useCallback(async (files: FileList | File[]) => {
    if (!files.length) return;
    if (uploadSummaryTimerRef.current !== null) window.clearTimeout(uploadSummaryTimerRef.current);
    setBusy(true);
    setUploadSummary({ uploaded: files.length, recognized: 0, scanning: true });
    try {
      const nextJob = await uploadInvoices(files);
      startTransition(() => {
        setRows((current) => appendPendingInvoices(current, nextJob.invoices));
        setUploadJob(nextJob);
        setUploadSummary({ uploaded: nextJob.total, recognized: nextJob.processed, scanning: isJobActive(nextJob.status) });
        setMutationVersion((version) => version + 1);
      });
      const warningCount = nextJob.invoices.filter((invoice) => pendingSupplierWarning(invoice)).length;
      if (isJobActive(nextJob.status)) toastRef.current.success(`Uploaded ${nextJob.total} files; previewing suppliers in parallel`);
      else if (warningCount) toastRef.current.info(`Uploaded ${nextJob.total} files; ${warningCount} need manual confirmation`);
      else toastRef.current.success(`Uploaded ${nextJob.total} files`);
    } catch (error) {
      setUploadSummary(null);
      toastRef.current.error(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }, []);

  const readyIds = useMemo(() => rows
    .filter((invoice) => pendingSupplierConfirmed(invoice) && !activeRecognitionIds.has(invoice.id))
    .map((invoice) => invoice.id), [activeRecognitionIds, rows]);

  useEffect(() => {
    setSelectedIds((ids) => {
      const next = new Set([...ids].filter((id) => readyIds.includes(id)));
      return next.size === ids.size ? ids : next;
    });
  }, [readyIds]);

  const startRecognition = useCallback(async (ids: number[]) => {
    const selectedReadyIds = ids.filter((id) => readyIds.includes(id));
    if (!selectedReadyIds.length) {
      toastRef.current.error("Select invoices with confirmed suppliers before recognition");
      return;
    }
    setBusy(true);
    try {
      const nextJob = await startRecognitionJob(selectedReadyIds);
      startTransition(() => {
        setRecognitionJob(nextJob);
        setActiveRecognitionIds(isJobActive(nextJob.status) ? new Set(selectedReadyIds) : new Set());
        setSelectedIds(new Set());
      });
      toastRef.current.success("Recognition job started");
    } catch (error) {
      setActiveRecognitionIds(new Set());
      toastRef.current.error(error instanceof Error ? error.message : "Failed to create recognition job");
    } finally {
      setBusy(false);
    }
  }, [readyIds]);

  const retryRow = useCallback(async (invoiceId: number) => {
    try {
      const nextJob = await retryInvoice(invoiceId);
      startTransition(() => {
        setRecognitionJob(nextJob);
        setActiveRecognitionIds(isJobActive(nextJob.status) ? new Set([invoiceId]) : new Set());
      });
      toastRef.current.success("Retry job started");
      await refresh();
    } catch (error) {
      setActiveRecognitionIds(new Set());
      toastRef.current.error(error instanceof Error ? error.message : "Retry failed");
    }
  }, [refresh]);

  const deleteRow = useCallback(async (invoice: Invoice) => {
    if (activeRecognitionIds.has(invoice.id)) {
      toastRef.current.error("This invoice is being recognized and cannot be deleted yet");
      return false;
    }
    if (!window.confirm(`Delete ${invoice.original_filename}? The file and database record will both be deleted.`)) return false;
    setDeletingId(invoice.id);
    try {
      await deleteInvoice(invoice.id);
      setRows((current) => current.filter((row) => row.id !== invoice.id));
      setSelectedIds((ids) => {
        const next = new Set(ids);
        next.delete(invoice.id);
        return next;
      });
      setMutationVersion((version) => version + 1);
      toastRef.current.success("Record and file deleted");
      await refresh();
      return true;
    } catch (error) {
      toastRef.current.error(error instanceof Error ? error.message : "Delete failed");
      return false;
    } finally {
      setDeletingId(null);
    }
  }, [activeRecognitionIds, refresh]);

  const deleteSelectedRows = useCallback(async () => {
    const selectedPendingIds = [...selectedIds].filter((id) => (
      rows.some((invoice) => invoice.id === id) && !activeRecognitionIds.has(id)
    ));
    if (!selectedPendingIds.length) {
      toastRef.current.error(activeRecognitionIds.size ? "Selected invoices are being recognized and cannot be deleted yet" : "Select pending invoices first");
      return;
    }
    if (!window.confirm(`Delete the selected ${selectedPendingIds.length} pending records? Files and database records will both be deleted.`)) return;
    setBusy(true);
    try {
      const results = await Promise.allSettled(selectedPendingIds.map((id) => deleteInvoice(id)));
      const success = results.filter((result) => result.status === "fulfilled").length;
      const failed = results.length - success;
      if (success) toastRef.current.success(`Deleted ${success} pending records`);
      if (failed) toastRef.current.error(`${failed} records failed to delete; please retry`);
      startTransition(() => {
        setSelectedIds(new Set());
        setMutationVersion((version) => version + 1);
      });
      await refresh();
    } catch (error) {
      toastRef.current.error(error instanceof Error ? error.message : "Bulk delete failed");
    } finally {
      setBusy(false);
    }
  }, [activeRecognitionIds, refresh, rows, selectedIds]);

  const updateSupplier = useCallback(async (invoice: Invoice, payload: {
    vendor_code: string;
    vendor_name: string;
    markAsInvoice: boolean;
  }) => {
    setUpdatingSupplierId(invoice.id);
    try {
      if (payload.markAsInvoice && !pendingDocumentIsInvoice(invoice)) {
        await saveExtractedData(invoice.id, {
          ...(invoice.extracted_data || {}),
          vendor_code: payload.vendor_code,
          vendor_name: payload.vendor_name,
          document_type: "invoice",
          document_is_invoice: "True",
          Is_Invoice: "True",
          document_type_reason: "manual_confirm_from_pending_drawer",
          supplier_warning: ""
        }, invoice.expense_type || "");
      }
      const updated = await confirmPendingSupplier(invoice.id, {
        vendor_code: payload.vendor_code,
        vendor_name: payload.vendor_name
      });
      setRows((current) => mergeInvoicesPreservingCurrentOrder(current, [updated]));
      toastRef.current.success(pendingSupplierConfirmed(updated) ? `Supplier confirmed: ${payload.vendor_name || payload.vendor_code}` : pendingSupplierWarning(updated));
      await refresh();
    } catch (error) {
      toastRef.current.error(error instanceof Error ? error.message : "Supplier confirmation failed");
    } finally {
      setUpdatingSupplierId(null);
    }
  }, [refresh]);

  const retrySupplierPreviewRow = useCallback(async (invoiceId: number) => {
    setPreviewRetryingId(invoiceId);
    try {
      const updated = await retrySupplierPreview(invoiceId);
      setRows((current) => mergeInvoicesPreservingCurrentOrder(current, [updated]));
      setMutationVersion((version) => version + 1);
      toastRef.current.success("Supplier preview completed again");
    } catch (error) {
      toastRef.current.error(error instanceof Error ? error.message : "Supplier preview retry failed");
    } finally {
      setPreviewRetryingId(null);
    }
  }, []);

  const toggleSelection = useCallback((id: number) => {
    if (!readyIds.includes(id)) return;
    setSelectedIds((ids) => {
      const next = new Set(ids);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, [readyIds]);

  const selectAll = useCallback((ids: number[]) => {
    setSelectedIds((current) => {
      const target = ids.filter((id) => readyIds.includes(id));
      const allSelected = target.length > 0 && target.every((id) => current.has(id));
      if (allSelected) return new Set([...current].filter((id) => !target.includes(id)));
      return new Set([...current, ...target]);
    });
  }, [readyIds]);

  const promptTagFor = useCallback((invoice: Invoice) => {
    const explicitTag = String(invoice.extracted_data?.prompt_tag || "").trim();
    if (explicitTag) return explicitTag;
    const code = String(invoice.vendor_code || invoice.extracted_data?.vendor_code || invoice.extracted_data?.supplier_code || "").trim();
    if (!code) return "default";
    return promptTagBySupplierCode[code] || promptTagBySupplierCode[normalizeSupplierInput(code)] || "default";
  }, [promptTagBySupplierCode]);

  const draftForSupplier = useCallback((invoice: Invoice, name: string) => {
    const supplier = suppliersByName.get(normalizeSupplierInput(name));
    return supplier ? { vendor_name: name, vendor_code: supplier.code } : { ...supplierDraftFor(invoice), vendor_name: name };
  }, [suppliersByName]);

  return {
    rows,
    suppliers,
    selectedIds,
    activeRecognitionIds,
    isLoading,
    busy,
    deletingId,
    updatingSupplierId,
    previewRetryingId,
    uploadSummary,
    recognitionActive: isJobActive(recognitionJob?.status),
    uploadActive: isJobActive(uploadJob?.status),
    readyIds,
    mutationVersion,
    refresh,
    uploadFiles,
    startRecognition,
    retryRow,
    retrySupplierPreviewRow,
    deleteRow,
    deleteSelectedRows,
    updateSupplier,
    toggleSelection,
    selectAll,
    promptTagFor,
    supplierDraftFor,
    draftForSupplier
  };
}
