import { useMemo } from "react";
import { expenseTypeOptions, fieldGroupLabels, standardFields } from "../lib/constants";
import type { FieldGroup as FieldGroupId } from "../lib/constants";
import { valueFor } from "../lib/format";
import {
  arrayRowsFromValue,
  isSystemExtractedDataKey,
  manualConfirmationFields
} from "../lib/invoice";
import { ensureFixedPromptFields, exportLabelForKey, normalizeFieldGroup, normalizeSupplierInput } from "../lib/prompt";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { Spinner } from "../ui/Spinner";
import { ArrayField } from "./ArrayField";
import { AutoArchiveCheckPanel } from "./AutoArchiveCheckPanel";
import { autoArchiveChecksForSupplierConfig, failedAutoArchiveFields } from "./autoArchiveChecks";
import { FieldGroup, type ReviewField } from "./FieldGroup";
import type { Invoice, PromptFieldConfig, PromptTag, Supplier, SupplierAutoArchiveCheck, SupplierAutoArchiveConfig } from "../types";
import type { ReviewDraft } from "./useReviewDraft";

type ReviewFormProps = {
  invoice: Invoice | null;
  draft: ReviewDraft;
  suppliers: Supplier[];
  promptTag: PromptTag | null;
  autoArchiveConfig: SupplierAutoArchiveConfig | null;
  disabled?: boolean;
  isDirty: boolean;
  isSaving: boolean;
  onFieldCommit: (key: string, value: string, fieldType?: PromptFieldConfig["type"]) => void;
  onSupplierCommit: (key: "vendor_code" | "vendor_name", value: string) => void;
  onExpenseTypeChange: (value: string) => void;
  onArrayChange: (key: string, rows: Record<string, unknown>[]) => void;
  onAutoArchiveCheckSave: (check: SupplierAutoArchiveCheck) => void;
  onCancel: () => void;
  onConfirm: () => void;
};

const groupOrder: FieldGroupId[] = ["supplier", "invoice", "amount", "line_items", "other"];
const reviewAutoAddExcludedFields = new Set(["invoice_category"]);

function canonicalFieldKey(key: string): string {
  return key.trim().toLowerCase();
}

function fieldLabelForKey(key: string): string {
  const match = standardFields.find(([fieldKey]) => fieldKey.toLowerCase() === key.toLowerCase());
  return match?.[1] || exportLabelForKey(key);
}

function fieldMatchesManual(key: string, manualFields: Set<string>): boolean {
  const canonical = canonicalFieldKey(key);
  return manualFields.has(canonical);
}

function buildFieldGroups(
  data: Record<string, unknown>,
  promptTag: PromptTag | null,
  autoArchiveFailedFields: Set<string>
): { groups: Record<FieldGroupId, ReviewField[]>; arrays: PromptFieldConfig[] } {
  const groups: Record<FieldGroupId, ReviewField[]> = {
    supplier: [],
    invoice: [],
    amount: [],
    line_items: [],
    other: []
  };
  const arrays: PromptFieldConfig[] = [];
  const seen = new Set<string>();
  const promptFields = ensureFixedPromptFields(promptTag?.fields || []);

  const addField = (field: PromptFieldConfig) => {
    const key = field.key.trim();
    const canonical = canonicalFieldKey(key);
    if (!key || seen.has(canonical) || field.type === "fixed") return;
    seen.add(canonical);
    if (field.type === "array") {
      arrays.push(field);
      return;
    }
    const group = normalizeFieldGroup(field.group, key, field.type);
    groups[group].push({
      key,
      label: fieldLabelForKey(key),
      type: field.type,
      autoArchiveFailed: autoArchiveFailedFields.has(canonical)
    });
  };

  promptFields.forEach(addField);
  standardFields.forEach(([key]) => {
    if (reviewAutoAddExcludedFields.has(canonicalFieldKey(key))) return;
    addField({ key, type: "string", group: normalizeFieldGroup(undefined, key, "string"), examples: "" });
  });

  Object.entries(data).forEach(([key, value]) => {
    const canonical = canonicalFieldKey(key);
    if (!key || seen.has(canonical) || isSystemExtractedDataKey(key)) return;
    if (Array.isArray(value)) {
      seen.add(canonical);
      arrays.push({ key, type: "array", group: "line_items", examples: "" });
    }
  });

  return { groups, arrays };
}

export function ReviewForm({
  invoice,
  draft,
  suppliers,
  promptTag,
  autoArchiveConfig,
  disabled = false,
  isDirty,
  isSaving,
  onFieldCommit,
  onSupplierCommit,
  onExpenseTypeChange,
  onArrayChange,
  onAutoArchiveCheckSave,
  onCancel,
  onConfirm
}: ReviewFormProps) {
  const supplierMaps = useMemo(() => ({
    byCode: new Map(suppliers.map((supplier) => [normalizeSupplierInput(supplier.code), supplier])),
    byName: new Map(suppliers.map((supplier) => [normalizeSupplierInput(supplier.name), supplier]))
  }), [suppliers]);

  const supplierValidation = useMemo(() => {
    if (!suppliers.length) return "";
    const code = valueFor(draft.data, "vendor_code");
    const name = valueFor(draft.data, "vendor_name");
    const normalizedCode = normalizeSupplierInput(code);
    const normalizedName = normalizeSupplierInput(name);
    if (!normalizedCode && !normalizedName) return "";
    const supplierByCode = normalizedCode ? supplierMaps.byCode.get(normalizedCode) : null;
    const supplierByName = normalizedName ? supplierMaps.byName.get(normalizedName) : null;
    if (normalizedCode && !supplierByCode) return "Vendor code is not in supplier.txt";
    if (normalizedName && !supplierByName) return "Vendor name is not in supplier.txt";
    if (supplierByCode && supplierByName && supplierByCode.code !== supplierByName.code) return "Vendor code and vendor name do not match";
    return "";
  }, [draft.data, supplierMaps, suppliers.length]);

  const manualFields = useMemo(
    () => new Set(manualConfirmationFields(draft.data).map(canonicalFieldKey)),
    [draft.data]
  );
  const autoArchiveFailedFields = useMemo(
    () => failedAutoArchiveFields(draft.data),
    [draft.data]
  );
  const autoArchiveChecks = useMemo(
    () => autoArchiveChecksForSupplierConfig(autoArchiveConfig),
    [autoArchiveConfig]
  );

  const grouped = useMemo(() => {
    const next = buildFieldGroups(draft.data, promptTag, autoArchiveFailedFields);
    groupOrder.forEach((group) => {
      next.groups[group] = next.groups[group].map((field) => ({
        ...field,
        requiredManualConfirmation: fieldMatchesManual(field.key, manualFields)
      }));
    });
    return next;
  }, [autoArchiveFailedFields, draft.data, manualFields, promptTag]);

  if (!invoice) {
    return (
      <aside className="flex h-full min-h-0 flex-col overflow-hidden rounded-card border border-ink-300/10 bg-card shadow-card">
        <div className="border-b border-ink-300/10 px-4 py-3">
          <h2 className="text-base font-semibold text-ink-900">Review Details</h2>
        </div>
        <div className="grid flex-1 place-items-center p-4">
          <EmptyState title="No review item selected" description="Select an invoice on the left to edit fields." />
        </div>
      </aside>
    );
  }

  return (
    <aside className="flex h-full min-h-0 flex-col overflow-hidden rounded-card border border-ink-300/10 bg-card shadow-card">
      <div className="flex items-start justify-between gap-2 border-b border-ink-300/10 px-3 py-2.5">
        <div className="min-w-0">
          <h2 className="truncate text-base font-semibold text-ink-900">Review Details</h2>
          <p className="mt-1 truncate text-xs text-ink-500">{invoice.original_filename}</p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5 pt-0.5">
          {isSaving ? <Spinner size="sm" label="Saving draft" /> : null}
          {isDirty ? <Badge variant="warn" className="whitespace-nowrap">Unsaved</Badge> : <Badge variant="neutral" className="whitespace-nowrap">Synced</Badge>}
          <Badge variant={invoice.status === "failed" ? "danger" : "ok"} className="whitespace-nowrap">
            {invoice.status === "failed" ? "Manual Entry" : "Needs Review"}
          </Badge>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto p-2">
        <div className="overflow-hidden rounded-soft border border-ink-300/10 bg-white shadow-card">
          <div className="grid grid-cols-[96px_minmax(0,1fr)] items-stretch transition-colors duration-fast ease-std hover:bg-brand-50/20">
            <span className="flex min-h-8 items-center border-r border-ink-300/10 bg-ink-300/[0.025] px-2 py-0.5 text-xs font-semibold text-ink-500">Expense Type</span>
            <div
              className="grid grid-cols-4 gap-1 p-1"
              role="radiogroup"
              aria-label="Expense Type"
            >
              {expenseTypeOptions.map((option) => (
                <button
                  key={option.value || "empty"}
                  type="button"
                  disabled={disabled}
                  role="radio"
                  aria-checked={draft.expenseType === option.value}
                  className={[
                    "flex h-8 min-w-0 items-center justify-center rounded-soft px-1 text-xs font-semibold leading-none transition-colors duration-micro",
                    draft.expenseType === option.value
                      ? "bg-brand-500 text-white shadow-sm"
                      : "bg-ink-300/10 text-ink-500 hover:bg-brand-50 hover:text-brand-700",
                    disabled ? "opacity-60" : ""
                  ].filter(Boolean).join(" ")}
                  onClick={() => onExpenseTypeChange(option.value)}
                >
                  <span className="truncate">{option.label === "Blank" ? "(blank)" : option.label}</span>
                </button>
              ))}
            </div>
          </div>

          {groupOrder.filter((group) => group !== "line_items").map((group) => {
            const fields = grouped.groups[group];
            const fieldsForRender = group === "supplier"
              ? fields.map((field) => ({
                ...field,
                label: field.key === "vendor_code" ? "Vendor Code" : field.key === "vendor_name" ? "Vendor Name" : field.label
              }))
              : fields;
            const commit = group === "supplier"
              ? (key: string, value: string, fieldType?: PromptFieldConfig["type"]) => {
                if (key === "vendor_code" || key === "vendor_name") onSupplierCommit(key, value);
                else onFieldCommit(key, value, fieldType);
              }
              : onFieldCommit;
            return (
              <FieldGroup
                key={group}
                title={fieldGroupLabels[group]}
                fields={fieldsForRender}
                draftData={draft.data}
                disabled={disabled}
                currency={group === "amount"}
                resetKey={invoice.id}
                onFieldCommit={commit}
              />
            );
          })}
        </div>

        {grouped.arrays.map((field) => {
          const rows = arrayRowsFromValue(draft.data[field.key]);
          return (
            <ArrayField
              key={field.key}
              field={field}
              rows={rows}
              disabled={disabled}
              onChange={(rows) => onArrayChange(field.key, rows)}
            />
          );
        })}

        {manualFields.size > 0 ? (
          <div className="rounded-soft bg-warn-bg px-3 py-2 text-xs font-semibold text-warn-text">
            Fields still requiring confirmation: {[...manualFields].join(", ")}
          </div>
        ) : null}

        {supplierValidation ? (
          <div className="rounded-soft bg-danger-bg px-3 py-2 text-xs font-semibold text-danger-text">
            {supplierValidation}
          </div>
        ) : null}
      </div>

      <div className="border-t border-ink-300/10 bg-white/90">
        <AutoArchiveCheckPanel
          checks={autoArchiveChecks}
          disabled={disabled}
          onSave={onAutoArchiveCheckSave}
        />
        <div className="flex items-center justify-end gap-2 px-3 py-2.5">
          <Button variant="ghost" disabled={disabled} onClick={onCancel}>Cancel</Button>
          <Button variant="primary" disabled={disabled || Boolean(supplierValidation)} onClick={onConfirm}>
            {disabled ? "Saving" : "Confirm Archive"}
          </Button>
        </div>
      </div>
    </aside>
  );
}
