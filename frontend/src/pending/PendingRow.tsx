import { memo } from "react";
import type { CSSProperties } from "react";
import { fileUrl } from "../api";
import {
  pendingDocumentTypeLabel,
  pendingSupplierConfidence,
  pendingSupplierRetry,
  pendingSupplierWarning
} from "../lib/invoice";
import type { Invoice } from "../types";
import { Badge } from "../ui/Badge";
import { IconButton } from "../ui/Button";
import { Dropdown } from "../ui/Dropdown";
import { Spinner } from "../ui/Spinner";
import { getPendingRowStatus, pendingFileTypeLabel } from "./helpers";

type PendingRowProps = {
  invoice: Invoice;
  selected: boolean;
  selectionDisabled: boolean;
  disabled: boolean;
  activeRecognitionIds: Set<number>;
  deleting: boolean;
  previewRetrying: boolean;
  rule: string;
  style?: CSSProperties;
  onToggle: (id: number) => void;
  onOpenWarning: (invoice: Invoice) => void;
  onRetryPreview: (id: number) => void;
  onDelete: (invoice: Invoice) => void;
};

function PendingRowComponent({
  invoice,
  selected,
  selectionDisabled,
  disabled,
  activeRecognitionIds,
  deleting,
  previewRetrying,
  rule,
  style,
  onToggle,
  onOpenWarning,
  onRetryPreview,
  onDelete
}: PendingRowProps) {
  const status = getPendingRowStatus(invoice, activeRecognitionIds);
  const rowBusy = status.isRecognizing || previewRetrying;
  const retry = status.isRecognizing ? pendingSupplierRetry(invoice) : null;
  const retryLabel = retry ? `Retry ${retry.attempt}/${retry.max}` : "";
  const confidence = pendingSupplierConfidence(invoice);
  const warning = pendingSupplierWarning(invoice);
  const supplier = invoice.vendor_name || String(invoice.extracted_data?.vendor_name || "").trim() || "Unnamed Supplier";
  const hasSpecialDocument = String(invoice.extracted_data?.special_document_matched || "").trim().toLowerCase() === "true";

  return (
    <div
      className={[
        "group grid h-full w-full grid-cols-[44px_minmax(220px,1.7fr)_minmax(160px,1fr)_120px_110px_90px_64px] items-center gap-3 border-b border-ink-300/15 bg-card px-3 text-sm",
        "transition-colors duration-micro ease-std hover:bg-brand-50",
        selected ? "bg-brand-50/70" : ""
      ].join(" ")}
      style={style}
      role="row"
      aria-selected={selected}
    >
      <span
        className={[
          "absolute left-0 top-2 h-[calc(100%-16px)] w-0.5 origin-center rounded-pill bg-brand-600 transition-transform duration-fast ease-in",
          selected ? "scale-y-100" : "scale-y-0"
        ].join(" ")}
        aria-hidden="true"
      />
      <div role="cell" className="flex items-center justify-center">
        <input
          className="size-4 rounded border-ink-300 accent-brand-600 disabled:opacity-35"
          type="checkbox"
          checked={selected}
          disabled={selectionDisabled}
          onChange={() => onToggle(invoice.id)}
          title={selectionDisabled ? "Confirm the supplier before recognition" : "Select for recognition"}
          aria-label={`Select ${invoice.original_filename}`}
        />
      </div>
      <div role="cell" className="min-w-0">
        <button
          type="button"
          className="flex max-w-full items-center gap-2 text-left font-semibold text-ink-900 outline-none hover:text-brand-700"
          onClick={() => window.open(fileUrl(invoice.id), "_blank", "noopener,noreferrer")}
          title={invoice.original_filename}
        >
          {rowBusy ? <Spinner size="sm" label={retryLabel || "Recognizing"} /> : null}
          {retryLabel ? (
            <span className="shrink-0 rounded-pill bg-warn-bg px-1.5 py-0.5 text-[11px] font-semibold text-warn-text" title="Model rate limit; retrying automatically">
              {retryLabel}
            </span>
          ) : null}
          <span className="truncate">{invoice.original_filename}</span>
        </button>
        <div className="mt-0.5 flex items-center gap-2 text-xs text-ink-500">
          <span>{pendingFileTypeLabel(invoice)}</span>
          <span aria-hidden="true">·</span>
          <span>{pendingDocumentTypeLabel(invoice)}</span>
        </div>
      </div>
      <div role="cell" className="min-w-0">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate font-medium text-ink-700" title={supplier}>{supplier}</span>
          <Badge variant={confidence >= 0.82 ? "ok" : "warn"}>{(confidence * 100).toFixed(0)}%</Badge>
        </div>
        <div className="mt-0.5 truncate text-xs text-ink-500">{invoice.vendor_code || String(invoice.extracted_data?.vendor_code || "").trim() || "No vendor code"}</div>
      </div>
      <div role="cell" className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-center gap-1">
          <Badge variant="neutral" className="max-w-full truncate">{rule}</Badge>
          {hasSpecialDocument ? (
            <Badge className="bg-brand-50/45 text-brand-600/70 ring-1 ring-brand-500/10">
              Preview Enabled
            </Badge>
          ) : null}
        </div>
      </div>
      <div role="cell">
        <Badge variant={rowBusy ? "neutral" : status.badgeVariant}>{rowBusy ? (retryLabel || "Recognizing") : status.label}</Badge>
      </div>
      <div role="cell">
        {status.filter === "needs-confirm" ? (
          <button
            type="button"
            className="inline-flex cursor-pointer items-center gap-1 rounded-pill border border-warn-text/20 bg-warn-bg px-2 py-1 text-xs font-semibold text-warn-text shadow-sm transition-all duration-fast ease-std hover:border-warn-text/50 hover:bg-warn-text hover:text-white hover:shadow-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-warn-text focus-visible:ring-offset-2"
            title={warning}
            onClick={() => onOpenWarning(invoice)}
          >
            <span aria-hidden="true">!</span>
            <span>Warning</span>
          </button>
        ) : (
          <span className="text-xs text-ink-300">-</span>
        )}
      </div>
      <div role="cell" className="flex justify-end">
        <Dropdown
          trigger={
            <IconButton
              aria-label={`${invoice.original_filename} Actions`}
              className="opacity-0 transition-opacity duration-micro group-hover:opacity-100 data-[state=open]:opacity-100"
            >
              ⋯
            </IconButton>
          }
          items={[
            { label: "View", onSelect: () => window.open(fileUrl(invoice.id), "_blank", "noopener,noreferrer") },
            { label: "Edit Supplier", onSelect: () => onOpenWarning(invoice) },
            { label: previewRetrying ? "Previewing" : "Retry Supplier Preview", disabled: disabled || deleting || previewRetrying, onSelect: () => onRetryPreview(invoice.id) },
            { label: deleting ? "Deleting" : "Delete", danger: true, disabled: disabled || deleting, onSelect: () => onDelete(invoice) }
          ]}
        />
      </div>
    </div>
  );
}

export const PendingRow = memo(PendingRowComponent, (prev, next) => (
  prev.invoice === next.invoice
  && prev.selected === next.selected
  && prev.selectionDisabled === next.selectionDisabled
  && prev.disabled === next.disabled
  && prev.deleting === next.deleting
  && prev.previewRetrying === next.previewRetrying
  && prev.rule === next.rule
  && prev.activeRecognitionIds === next.activeRecognitionIds
));
