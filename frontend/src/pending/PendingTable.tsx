import { AnimatePresence, motion } from "motion/react";
import { useMemo, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { Invoice } from "../types";
import { EmptyState } from "../ui/EmptyState";
import { SpinnerPanel } from "../ui/Spinner";
import { filterPendingRows, getPendingRowStatus, type PendingFilter } from "./helpers";
import { PendingRow } from "./PendingRow";

type PendingTableProps = {
  rows: Invoice[];
  filter: PendingFilter;
  selectedIds: Set<number>;
  activeRecognitionIds: Set<number>;
  isLoading: boolean;
  deletingId: number | null;
  previewRetryingId: number | null;
  mutationVersion: number;
  promptTagFor: (invoice: Invoice) => string;
  onToggle: (id: number) => void;
  onSelectAll: (ids: number[]) => void;
  onOpenWarning: (invoice: Invoice) => void;
  onRetryPreview: (id: number) => void;
  onDelete: (invoice: Invoice) => void;
};

const rowHeight = 76;

export function PendingTable({
  rows,
  filter,
  selectedIds,
  activeRecognitionIds,
  isLoading,
  deletingId,
  previewRetryingId,
  mutationVersion,
  promptTagFor,
  onToggle,
  onSelectAll,
  onOpenWarning,
  onRetryPreview,
  onDelete
}: PendingTableProps) {
  const parentRef = useRef<HTMLDivElement | null>(null);
  const visibleRows = useMemo(
    () => filterPendingRows(rows, filter, activeRecognitionIds),
    [activeRecognitionIds, filter, rows]
  );
  const selectableIds = useMemo(
    () => visibleRows
      .filter((invoice) => getPendingRowStatus(invoice, activeRecognitionIds).filter === "ready")
      .map((invoice) => invoice.id),
    [activeRecognitionIds, visibleRows]
  );
  const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selectedIds.has(id));
  const virtualizer = useVirtualizer({
    count: visibleRows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => rowHeight,
    overscan: 8
  });

  if (isLoading) return <SpinnerPanel label="Loading pending invoices" />;

  return (
    <div className="overflow-hidden rounded-card border border-ink-300/10 bg-card shadow-card" role="table" aria-label="Pending invoices">
      <div
        className="sticky top-0 z-10 grid grid-cols-[44px_minmax(220px,1.7fr)_minmax(160px,1fr)_120px_110px_90px_64px] items-center gap-3 border-b border-ink-300/15 bg-card px-3 py-3 text-xs font-semibold uppercase tracking-[0.04em] text-ink-500"
        role="row"
      >
        <div role="columnheader" className="flex justify-center">
          <input
            className="size-4 rounded border-ink-300 accent-brand-600"
            type="checkbox"
            checked={allSelected}
            disabled={!selectableIds.length}
            onChange={() => onSelectAll(selectableIds)}
            aria-label="Select all filtered results"
          />
        </div>
        <div role="columnheader">File Name</div>
        <div role="columnheader">Supplier</div>
        <div role="columnheader">Rules</div>
        <div role="columnheader">Status</div>
        <div role="columnheader">Warning</div>
        <div role="columnheader" className="text-right">Actions</div>
      </div>

      {!visibleRows.length ? (
        <EmptyState
          title={rows.length ? "No pending invoices match the current filter" : "No pending invoices"}
          description={rows.length ? "Switch the status filter above to view other pending files." : "Upload files to see supplier preview results."}
        />
      ) : (
        <div ref={parentRef} className="max-h-[62vh] min-h-[320px] overflow-auto" role="rowgroup">
          <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
            <AnimatePresence initial={false} mode="popLayout">
              {virtualizer.getVirtualItems().map((virtualRow) => {
                const invoice = visibleRows[virtualRow.index];
                if (!invoice) return null;
                const status = getPendingRowStatus(invoice, activeRecognitionIds);
                return (
                  <motion.div
                    key={invoice.id}
                    layout
                    initial={mutationVersion ? { opacity: 0, y: -6 } : false}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 6 }}
                    transition={{ duration: 0.18, ease: [0, 0, 0.2, 1] }}
                    className="absolute left-0 top-0 w-full"
                    style={{
                      height: virtualRow.size,
                      top: virtualRow.start
                    }}
                  >
                    <PendingRow
                      invoice={invoice}
                      selected={status.filter === "ready" && selectedIds.has(invoice.id)}
                      selectionDisabled={status.filter !== "ready"}
                      disabled={status.isRecognizing}
                      activeRecognitionIds={activeRecognitionIds}
                      deleting={deletingId === invoice.id}
                      previewRetrying={previewRetryingId === invoice.id}
                      rule={promptTagFor(invoice)}
                      onToggle={onToggle}
                      onOpenWarning={onOpenWarning}
                      onRetryPreview={onRetryPreview}
                      onDelete={onDelete}
                    />
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </div>
        </div>
      )}
    </div>
  );
}
