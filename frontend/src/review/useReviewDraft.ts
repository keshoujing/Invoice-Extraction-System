import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { persistExtractedDataInBackground, saveExtractedData, saveManualEntry } from "../api";
import { clearManualConfirmationForField } from "../lib/invoice";
import { setValueFor } from "../lib/format";
import type { Invoice, PromptFieldConfig } from "../types";

export type ReviewDraft = {
  data: Record<string, unknown>;
  expenseType: string;
};

type DraftRecord = ReviewDraft & {
  savedSignature: string;
};

type UseReviewDraftResult = {
  draft: ReviewDraft;
  updateField: (key: string, value: unknown, fieldType?: PromptFieldConfig["type"]) => void;
  updateFields: (updates: Array<{ key: string; value: unknown; fieldType?: PromptFieldConfig["type"] }>) => void;
  updateExpenseType: (expenseType: string) => void;
  replaceArrayField: (key: string, rows: Record<string, unknown>[]) => void;
  reset: () => void;
  save: () => Promise<Invoice | null>;
  isDirty: boolean;
  isSaving: boolean;
};

function cloneData(data: Record<string, unknown> | undefined): Record<string, unknown> {
  return { ...(data || {}) };
}

function draftSignature(invoiceId: number | null, draft: ReviewDraft): string {
  return JSON.stringify({ invoiceId, data: draft.data, expenseType: draft.expenseType });
}

function coerceFieldValue(value: unknown, fieldType?: PromptFieldConfig["type"]): unknown {
  if (fieldType === "array" && typeof value === "string") {
    try {
      return JSON.parse(value);
    } catch {
      return value;
    }
  }
  if (fieldType === "bool") return value === true || String(value).trim().toLowerCase() === "true";
  return value;
}

function recordForInvoice(invoice: Invoice): DraftRecord {
  const draft = {
    data: cloneData(invoice.extracted_data),
    expenseType: invoice.expense_type || ""
  };
  return {
    ...draft,
    savedSignature: draftSignature(invoice.id, draft)
  };
}

export function useReviewDraft(invoice: Invoice | null, onError?: (message: string) => void): UseReviewDraftResult {
  const draftsRef = useRef(new Map<number, DraftRecord>());
  const [draft, setDraft] = useState<ReviewDraft>({ data: {}, expenseType: "" });
  const [savedSignature, setSavedSignature] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const invoiceId = invoice?.id ?? null;

  useEffect(() => {
    if (!invoice) {
      setDraft({ data: {}, expenseType: "" });
      setSavedSignature("");
      return;
    }
    const record = draftsRef.current.get(invoice.id) || recordForInvoice(invoice);
    draftsRef.current.set(invoice.id, record);
    setDraft({ data: cloneData(record.data), expenseType: record.expenseType });
    setSavedSignature(record.savedSignature);
  }, [invoice]);

  const writeRecord = useCallback((next: ReviewDraft, nextSavedSignature?: string) => {
    if (!invoiceId) return;
    const record = draftsRef.current.get(invoiceId);
    draftsRef.current.set(invoiceId, {
      data: cloneData(next.data),
      expenseType: next.expenseType,
      savedSignature: nextSavedSignature ?? record?.savedSignature ?? ""
    });
  }, [invoiceId]);

  const applyDraft = useCallback((updater: (current: ReviewDraft) => ReviewDraft) => {
    setDraft((current) => {
      const next = updater(current);
      writeRecord(next);
      return next;
    });
  }, [writeRecord]);

  const updateFields = useCallback((updates: Array<{ key: string; value: unknown; fieldType?: PromptFieldConfig["type"] }>) => {
    applyDraft((current) => {
      let nextData = current.data;
      updates.forEach((update) => {
        nextData = setValueFor(nextData, update.key, coerceFieldValue(update.value, update.fieldType));
        nextData = clearManualConfirmationForField(nextData, update.key);
      });
      return { ...current, data: nextData };
    });
  }, [applyDraft]);

  const updateField = useCallback((key: string, value: unknown, fieldType?: PromptFieldConfig["type"]) => {
    updateFields([{ key, value, fieldType }]);
  }, [updateFields]);

  const updateExpenseType = useCallback((expenseType: string) => {
    applyDraft((current) => ({ ...current, expenseType }));
  }, [applyDraft]);

  const replaceArrayField = useCallback((key: string, rows: Record<string, unknown>[]) => {
    applyDraft((current) => ({
      ...current,
      data: clearManualConfirmationForField(setValueFor(current.data, key, rows), key)
    }));
  }, [applyDraft]);

  const reset = useCallback(() => {
    if (!invoice) return;
    const record = recordForInvoice(invoice);
    draftsRef.current.set(invoice.id, record);
    setDraft({ data: cloneData(record.data), expenseType: record.expenseType });
    setSavedSignature(record.savedSignature);
  }, [invoice]);

  const currentSignature = useMemo(() => draftSignature(invoiceId, draft), [draft, invoiceId]);
  const isDirty = Boolean(invoiceId && currentSignature !== savedSignature);

  const markSaved = useCallback((signature: string, savedDraft: ReviewDraft) => {
    setSavedSignature(signature);
    writeRecord(savedDraft, signature);
  }, [writeRecord]);

  const save = useCallback(async () => {
    if (!invoice) return null;
    const draftToSave = { data: cloneData(draft.data), expenseType: draft.expenseType };
    const signature = draftSignature(invoice.id, draftToSave);
    setIsSaving(true);
    try {
      const saved = invoice.status === "failed"
        ? await saveManualEntry(invoice.id, draftToSave.data, draftToSave.expenseType)
        : await saveExtractedData(invoice.id, draftToSave.data, draftToSave.expenseType);
      markSaved(signature, draftToSave);
      return saved;
    } finally {
      setIsSaving(false);
    }
  }, [draft, invoice, markSaved]);

  useEffect(() => {
    if (!invoice || invoice.status !== "recognized" || !isDirty) return;
    const draftToSave = { data: cloneData(draft.data), expenseType: draft.expenseType };
    const signature = draftSignature(invoice.id, draftToSave);
    const timer = window.setTimeout(async () => {
      setIsSaving(true);
      try {
        await saveExtractedData(invoice.id, draftToSave.data, draftToSave.expenseType);
        markSaved(signature, draftToSave);
      } catch (err) {
        onError?.(err instanceof Error ? err.message : "Failed to save review draft");
      } finally {
        setIsSaving(false);
      }
    }, 500);
    return () => window.clearTimeout(timer);
  }, [draft, invoice, isDirty, markSaved, onError]);

  useEffect(() => {
    if (!invoice || invoice.status !== "recognized") return;
    const flushDraft = () => {
      const signature = draftSignature(invoice.id, draft);
      if (signature === savedSignature) return;
      persistExtractedDataInBackground(invoice.id, draft.data, draft.expenseType);
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") flushDraft();
    };
    window.addEventListener("pagehide", flushDraft);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      window.removeEventListener("pagehide", flushDraft);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [draft, invoice, savedSignature]);

  return {
    draft,
    updateField,
    updateFields,
    updateExpenseType,
    replaceArrayField,
    reset,
    save,
    isDirty,
    isSaving
  };
}
