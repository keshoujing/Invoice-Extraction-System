import { useVirtualizer } from "@tanstack/react-virtual";
import { memo, useRef } from "react";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { reviewListActionsForInvoice } from "./reviewListActions";
import type { Invoice } from "../types";

type ReviewListProps = {
  successful: Invoice[];
  failed: Invoice[];
  selectedInvoiceId: number | null;
  deletingInvoiceId: number | null;
  retryingInvoiceId: number | null;
  onSelect: (invoice: Invoice) => void;
  onRetry: (invoiceId: number) => void;
  onDelete: (invoice: Invoice) => void;
};

type ReviewListEntry =
  | { type: "header"; key: string; title: string; count: number }
  | { type: "empty"; key: string; message: string }
  | { type: "invoice"; key: string; invoice: Invoice };

type ItemProps = {
  invoice: Invoice;
  selected: boolean;
  deleting: boolean;
  retrying: boolean;
  onSelect: (invoice: Invoice) => void;
  onRetry: (invoiceId: number) => void;
  onDelete: (invoice: Invoice) => void;
};

function amountText(invoice: Invoice): string {
  const amount = Number(invoice.total_amount || invoice.extracted_data?.total_amount || 0);
  if (!Number.isFinite(amount)) return "0.00";
  return amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const ReviewListItem = memo(function ReviewListItem({
  invoice,
  selected,
  deleting,
  retrying,
  onSelect,
  onRetry,
  onDelete
}: ItemProps) {
  const isFailed = invoice.status === "failed";
  const actions = reviewListActionsForInvoice(invoice);
  const canRetry = actions.includes("retry");
  const canDelete = actions.includes("delete");

  return (
    <article
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={() => onSelect(invoice)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect(invoice);
        }
      }}
      className={[
        "group rounded-soft border p-2.5 text-left outline-none transition-[background,border-color,box-shadow] duration-fast ease-std",
        selected ? "border-brand-500/40 bg-brand-50 shadow-card" : "border-ink-300/15 bg-white hover:border-brand-500/25 hover:bg-brand-50/60",
        isFailed ? "border-danger-text/20" : ""
      ].filter(Boolean).join(" ")}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-ink-900">
            {isFailed ? invoice.original_filename : invoice.vendor_name || "Unrecognized Supplier"}
          </h3>
          <p className="mt-1 truncate text-xs text-ink-500">
            {isFailed ? invoice.error_message || "Recognition Failed" : invoice.invoice_number || invoice.original_filename}
          </p>
        </div>
        <Badge variant={isFailed ? "danger" : "ok"} className="shrink-0 whitespace-nowrap">
          {isFailed ? "Failed" : "Needs Review"}
        </Badge>
      </div>
      {!isFailed ? (
        <div className="mt-2 flex items-center justify-between gap-2 text-xs text-ink-500">
          <span>{invoice.invoice_date || "No Date"}</span>
          <div className="flex shrink-0 items-center gap-2">
            <span className="font-mono font-semibold text-ink-700">{amountText(invoice)}</span>
            {canDelete ? (
              <Button
                variant="danger"
                className="min-h-7 px-2 py-0.5 text-xs"
                disabled={deleting}
                onClick={(event) => {
                  event.stopPropagation();
                  onDelete(invoice);
                }}
              >
                {deleting ? "Deleting" : "Delete"}
              </Button>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="mt-2 flex items-center gap-2">
          {canRetry ? (
            <Button
              variant="ghost"
              className="min-h-8 px-2.5 py-1 text-xs"
              disabled={retrying || deleting}
              onClick={(event) => {
                event.stopPropagation();
                onRetry(invoice.id);
              }}
            >
              {retrying ? "Retrying" : "Retry"}
            </Button>
          ) : null}
          {canDelete ? (
            <Button
              variant="danger"
              className="min-h-8 px-2.5 py-1 text-xs"
              disabled={deleting || retrying}
              onClick={(event) => {
                event.stopPropagation();
                onDelete(invoice);
              }}
            >
              {deleting ? "Deleting" : "Delete"}
            </Button>
          ) : null}
        </div>
      )}
    </article>
  );
});

function SectionHeader({ title, count }: { title: string; count: number }) {
  return (
    <div className="flex items-center justify-between px-1 pb-1.5 pt-0.5">
      <span className="text-xs font-semibold text-ink-500">{title}</span>
      <span className="font-mono text-xs text-ink-300">{count}</span>
    </div>
  );
}

function EmptySectionMessage({ children }: { children: string }) {
  return <div className="rounded-soft border border-dashed border-ink-300/15 px-3 py-4 text-center text-xs text-ink-300">{children}</div>;
}

function buildEntries(successful: Invoice[], failed: Invoice[]): ReviewListEntry[] {
  return [
    { type: "header", key: "success-header", title: "Recognition Successful", count: successful.length },
    ...(successful.length
      ? successful.map((invoice) => ({ type: "invoice" as const, key: `invoice-${invoice.id}`, invoice }))
      : [{ type: "empty" as const, key: "success-empty", message: "No successfully recognized files" }]),
    { type: "header", key: "failed-header", title: "Recognition Failed / Non-Invoice", count: failed.length },
    ...(failed.length
      ? failed.map((invoice) => ({ type: "invoice" as const, key: `invoice-${invoice.id}`, invoice }))
      : [{ type: "empty" as const, key: "failed-empty", message: "No failed or non-invoice files" }])
  ];
}

function VirtualList({
  entries,
  selectedInvoiceId,
  deletingInvoiceId,
  retryingInvoiceId,
  onSelect,
  onRetry,
  onDelete
}: Omit<ReviewListProps, "successful" | "failed"> & { entries: ReviewListEntry[] }) {
  const parentRef = useRef<HTMLDivElement | null>(null);
  const rowVirtualizer = useVirtualizer({
    count: entries.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => {
      const entry = entries[index];
      if (entry?.type === "header") return 30;
      if (entry?.type === "empty") return 56;
      return 84;
    },
    overscan: 8
  });

  return (
    <div ref={parentRef} className="h-full min-h-0 overflow-y-auto pr-1">
      <div className="relative w-full" style={{ height: rowVirtualizer.getTotalSize() }}>
        {rowVirtualizer.getVirtualItems().map((virtualRow) => {
          const entry = entries[virtualRow.index];
          if (!entry) return null;
          return (
            <div
              key={entry.key}
              className="absolute left-0 top-0 w-full pb-2"
              style={{ transform: `translateY(${virtualRow.start}px)` }}
            >
              {entry.type === "header" ? <SectionHeader title={entry.title} count={entry.count} /> : null}
              {entry.type === "empty" ? <EmptySectionMessage>{entry.message}</EmptySectionMessage> : null}
              {entry.type === "invoice" ? (
                <ReviewListItem
                  invoice={entry.invoice}
                  selected={selectedInvoiceId === entry.invoice.id}
                  deleting={deletingInvoiceId === entry.invoice.id}
                  retrying={retryingInvoiceId === entry.invoice.id}
                  onSelect={onSelect}
                  onRetry={onRetry}
                  onDelete={onDelete}
                />
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function ReviewList(props: ReviewListProps) {
  const total = props.successful.length + props.failed.length;
  const entries = buildEntries(props.successful, props.failed);

  return (
    <aside className="flex h-full min-h-0 flex-col overflow-hidden rounded-card border border-ink-300/10 bg-card shadow-card">
      <div className="flex items-center justify-between border-b border-ink-300/10 px-3 py-2.5">
        <span className="text-sm font-semibold text-ink-900">Review Queue</span>
        <span className="font-mono text-xs text-ink-300">{total}</span>
      </div>
      <div className="min-h-0 flex-1 p-2">
        {!total ? (
          <EmptyState title="No review items" description="There are no invoices requiring manual review." />
        ) : total > 50 ? (
          <VirtualList entries={entries} {...props} />
        ) : (
          <div className="h-full min-h-0 space-y-1.5 overflow-y-auto pr-1">
            <SectionHeader title="Recognition Successful" count={props.successful.length} />
            {props.successful.length ? (
              props.successful.map((invoice) => (
                <ReviewListItem
                  key={invoice.id}
                  invoice={invoice}
                  selected={props.selectedInvoiceId === invoice.id}
                  deleting={props.deletingInvoiceId === invoice.id}
                  retrying={props.retryingInvoiceId === invoice.id}
                  onSelect={props.onSelect}
                  onRetry={props.onRetry}
                  onDelete={props.onDelete}
                />
              ))
            ) : (
              <EmptySectionMessage>No successfully recognized files</EmptySectionMessage>
            )}
            <SectionHeader title="Recognition Failed / Non-Invoice" count={props.failed.length} />
            {props.failed.length ? (
              props.failed.map((invoice) => (
                <ReviewListItem
                  key={invoice.id}
                  invoice={invoice}
                  selected={props.selectedInvoiceId === invoice.id}
                  deleting={props.deletingInvoiceId === invoice.id}
                  retrying={props.retryingInvoiceId === invoice.id}
                  onSelect={props.onSelect}
                  onRetry={props.onRetry}
                  onDelete={props.onDelete}
                />
              ))
            ) : (
              <EmptySectionMessage>No failed or non-invoice files</EmptySectionMessage>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
