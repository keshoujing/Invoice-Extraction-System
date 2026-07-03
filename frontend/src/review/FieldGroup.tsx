import { memo, useEffect, useMemo, useState } from "react";
import { fieldValueForDisplay } from "../lib/format";
import { Badge } from "../ui/Badge";
import type { PromptFieldConfig } from "../types";

export type ReviewField = {
  key: string;
  label: string;
  type: PromptFieldConfig["type"];
  requiredManualConfirmation?: boolean;
  autoArchiveFailed?: boolean;
};

type FieldGroupProps = {
  title: string;
  fields: ReviewField[];
  draftData: Record<string, unknown>;
  disabled?: boolean;
  currency?: boolean;
  resetKey: string | number;
  onFieldCommit: (key: string, value: string, fieldType?: PromptFieldConfig["type"]) => void;
};

function valueIsFilled(value: string): boolean {
  return value.trim().length > 0;
}

function inputModeFor(field: ReviewField): "text" | "textarea" | "bool" {
  if (field.type === "bool" || isBooleanLikeField(field.key)) return "bool";
  if (field.key.length > 26 || fieldValueHint(field.key)) return "textarea";
  return "text";
}

function isBooleanLikeField(key: string): boolean {
  const normalized = key.trim().toLowerCase();
  return normalized === "is_invoice";
}

function fieldValueHint(key: string): boolean {
  const lowered = key.toLowerCase();
  return lowered.includes("reason") || lowered.includes("description") || lowered.includes("memo") || lowered.includes("note");
}

function localValuesFor(fields: ReviewField[], data: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(fields.map((field) => {
    const value = fieldValueForDisplay(data, field.key);
    return [field.key, isInvoiceDateField(field.key) ? invoiceDateInputValue(value) : value];
  }));
}

function isInvoiceDateField(key: string): boolean {
  return key.trim().toLowerCase() === "invoice_date" || key.trim() === "Invoice Date";
}

function invoiceDateInputValue(value: string): string {
  const trimmed = value.trim();
  const isoMatch = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/.exec(trimmed);
  if (isoMatch) return `${isoMatch[2].padStart(2, "0")}/${isoMatch[3].padStart(2, "0")}/${isoMatch[1]}`;
  const usMatch = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})$/.exec(trimmed);
  if (usMatch) {
    const year = usMatch[3].length === 2 ? `20${usMatch[3]}` : usMatch[3];
    return `${usMatch[1].padStart(2, "0")}/${usMatch[2].padStart(2, "0")}/${year}`;
  }
  return formatInvoiceDateDigits(trimmed.replace(/\D/g, "").slice(0, 8));
}

function formatInvoiceDateDigits(digits: string): string {
  if (digits.length <= 2) return digits;
  if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`;
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
}

function isValidInvoiceDateInput(value: string): boolean {
  if (!/^\d{2}\/\d{2}\/\d{4}$/.test(value)) return false;
  const month = Number(value.slice(0, 2));
  const day = Number(value.slice(3, 5));
  const year = Number(value.slice(6));
  const parsed = new Date(year, month - 1, day);
  return (
    parsed.getFullYear() === year
    && parsed.getMonth() === month - 1
    && parsed.getDate() === day
  );
}

function normalizedBoolValue(value: string): "" | "true" | "false" {
  const normalized = value.trim().toLowerCase();
  if (normalized === "true") return "true";
  if (normalized === "false") return "false";
  return "";
}

const listControlClasses = [
  "block h-6 w-full border-0 bg-transparent px-2 py-0 text-sm leading-5 text-ink-900 outline-none",
  "transition-[background,box-shadow] duration-micro ease-std placeholder:text-ink-300",
  "focus:bg-brand-50/70 focus:ring-1 focus:ring-inset focus:ring-brand-500/30",
  "disabled:pointer-events-none disabled:opacity-60"
].join(" ");

export const FieldGroup = memo(function FieldGroup({
  title,
  fields,
  draftData,
  disabled = false,
  currency = false,
  resetKey,
  onFieldCommit
}: FieldGroupProps) {
  const [localValues, setLocalValues] = useState<Record<string, string>>(() => localValuesFor(fields, draftData));

  useEffect(() => {
    setLocalValues(localValuesFor(fields, draftData));
  }, [draftData, fields, resetKey]);

  const completion = useMemo(() => {
    const total = fields.length;
    const filled = fields.filter((field) => valueIsFilled(localValues[field.key] || "")).length;
    return { filled, total };
  }, [fields, localValues]);

  if (!fields.length) return null;

  return (
    <section className="border-t border-ink-300/10">
      <div className="flex h-7 items-center justify-between gap-3 bg-ink-300/[0.05] px-2.5">
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="truncate text-[11px] font-semibold text-ink-700">{title}</span>
          {currency ? (
            <span className="flex size-5 shrink-0 items-center justify-center rounded-pill bg-ok-bg text-[11px] font-bold leading-none text-ok-text">
              $
            </span>
          ) : null}
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          {fields.some((field) => field.requiredManualConfirmation) ? <Badge variant="warn" className="whitespace-nowrap text-[11px]">Needs Confirmation</Badge> : null}
          <Badge variant="neutral" className="whitespace-nowrap text-[11px]">{completion.filled}/{completion.total}</Badge>
        </span>
      </div>
      <div className="divide-y divide-ink-300/10">
        {fields.map((field) => {
          const mode = inputModeFor(field);
          const value = localValues[field.key] || "";
          const isInvoiceDate = isInvoiceDateField(field.key);
          const rowClassName = [
            "grid grid-cols-[96px_minmax(0,1fr)] items-stretch transition-colors duration-fast ease-std hover:bg-brand-50/20",
            field.requiredManualConfirmation ? "bg-warn-bg/25" : "",
            field.autoArchiveFailed ? "bg-danger-bg/20" : ""
          ].filter(Boolean).join(" ");
          const controlClassName = [
            listControlClasses,
            field.autoArchiveFailed ? "text-danger-text focus:bg-danger-bg/30 focus:ring-danger-text/30" : ""
          ].filter(Boolean).join(" ");

          const boolValue = normalizedBoolValue(value);

          return (
            <div key={field.key} className={rowClassName}>
              <div className={[
                "flex min-h-6 min-w-0 flex-col justify-center border-r border-ink-300/10 bg-ink-300/[0.025] px-2 py-0",
                field.autoArchiveFailed ? "bg-danger-bg/40" : ""
              ].filter(Boolean).join(" ")}>
                <span className={[
                  "block truncate text-xs font-semibold",
                  field.autoArchiveFailed ? "text-danger-text" : "text-ink-500"
                ].filter(Boolean).join(" ")}>{field.label}</span>
                {field.requiredManualConfirmation ? <Badge variant="warn" className="mt-1 whitespace-nowrap text-[11px]">Needs Confirmation</Badge> : null}
              </div>
              <div className="flex min-h-6 min-w-0 items-center px-0.5 py-0">
                {mode === "bool" ? (
                  <div
                    className="grid h-6 w-full grid-cols-3 gap-1 px-1"
                    role="radiogroup"
                    aria-label={field.label}
                  >
                    {[
                      { value: "", label: "Blank" },
                      { value: "True", label: "True" },
                      { value: "False", label: "False" }
                    ].map((option) => {
                      const selected = normalizedBoolValue(option.value) === boolValue;
                      return (
                        <button
                          key={option.label}
                          type="button"
                          disabled={disabled}
                          role="radio"
                          aria-checked={selected}
                          className={[
                            "flex min-w-0 items-center justify-center rounded-soft px-1 text-xs font-semibold leading-none transition-colors duration-micro",
                            selected ? "bg-brand-500 text-white shadow-sm" : "bg-transparent text-ink-500 hover:bg-brand-50 hover:text-brand-700",
                            disabled ? "opacity-60" : ""
                          ].filter(Boolean).join(" ")}
                          onClick={() => {
                            setLocalValues((current) => ({ ...current, [field.key]: option.value }));
                            onFieldCommit(field.key, option.value, field.type);
                          }}
                        >
                          <span className="truncate">{option.label}</span>
                        </button>
                      );
                    })}
                  </div>
                ) : mode === "textarea" ? (
                  <textarea
                    className={[controlClassName, "h-auto min-h-10 resize-y py-1"].join(" ")}
                    value={value}
                    disabled={disabled}
                    rows={2}
                    onChange={(event) => setLocalValues((current) => ({ ...current, [field.key]: event.target.value }))}
                    onBlur={(event) => onFieldCommit(field.key, event.target.value, field.type)}
                  />
                ) : (
                  <input
                    value={value}
                    disabled={disabled}
                    className={controlClassName}
                    inputMode={isInvoiceDate ? "numeric" : undefined}
                    maxLength={isInvoiceDate ? 10 : undefined}
                    placeholder={isInvoiceDate ? "MM/DD/YYYY" : undefined}
                    onChange={(event) => {
                      const nextValue = isInvoiceDate
                        ? invoiceDateInputValue(event.target.value)
                        : event.target.value;
                      setLocalValues((current) => ({ ...current, [field.key]: nextValue }));
                    }}
                    onBlur={(event) => {
                      if (!isInvoiceDate) {
                        onFieldCommit(field.key, event.target.value, field.type);
                        return;
                      }
                      const nextValue = invoiceDateInputValue(event.target.value);
                      if (!nextValue || isValidInvoiceDateInput(nextValue)) {
                        onFieldCommit(field.key, nextValue, field.type);
                        return;
                      }
                      setLocalValues((current) => ({
                        ...current,
                        [field.key]: invoiceDateInputValue(fieldValueForDisplay(draftData, field.key))
                      }));
                    }}
                  />
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
});
