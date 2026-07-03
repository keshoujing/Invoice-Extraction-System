import { memo, useMemo, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { ExportStatus, Invoice } from "../types";
import { fileUrl } from "../api";
import { expenseTypeOptions } from "../lib/constants";
import { displayDate, formatAmount } from "../lib/format";
import { Button } from "../ui/Button";
import { ColumnFilter } from "./ColumnFilter";
import type {
  ConfirmedColumnKey,
  ConfirmedFilters,
  ConfirmedSort,
  ConfirmedSortKey
} from "./useConfirmedFilters";
import { hasExportRecord } from "./useConfirmedFilters";

type RowItem =
  | { type: "batch"; key: string; label: string; count: number }
  | { type: "invoice"; key: string; invoice: Invoice };

type FilterOption = {
  value: string;
  label: string;
};

type ConfirmedTableProps = {
  rows: Invoice[];
  allRows: Invoice[];
  categories: string[];
  filters: ConfirmedFilters;
  rangeFilter: ExportStatus;
  sort: ConfirmedSort;
  selectedIds: Set<number>;
  loading: boolean;
  hasActiveFilters: boolean;
  onPatchFilters: (patch: Partial<ConfirmedFilters>) => void;
  onClearColumn: (column: ConfirmedColumnKey) => void;
  onSort: (sort: ConfirmedSort) => void;
  onToggleRow: (id: number) => void;
  onToggleAll: () => void;
  onResetFilters: () => void;
};

const gridTemplate = "44px 96px 120px 124px 190px 120px 140px 120px 120px 96px 72px";

const columns: Array<{ key: ConfirmedColumnKey; label: string; sortable?: boolean }> = [
  { key: "expense_type", label: "Expense Type", sortable: false },
  { key: "invoice_category", label: "Invoice Category", sortable: false },
  { key: "vendor_code", label: "Vendor Code" },
  { key: "vendor_name", label: "Vendor Name" },
  { key: "po_number", label: "PO" },
  { key: "invoice_number", label: "Invoice Number" },
  { key: "invoice_date", label: "Invoice Date" },
  { key: "total_amount", label: "Amount" },
  { key: "status", label: "Status", sortable: false }
];

function uniqueOptions(values: string[], emptyLabel = "Blank"): FilterOption[] {
  const seen = new Set<string>();
  const options: FilterOption[] = [];
  values.forEach((value) => {
    const key = value.trim() || "__empty__";
    if (seen.has(key)) return;
    seen.add(key);
    options.push({ value: key, label: key === "__empty__" ? emptyLabel : key });
  });
  return options;
}

function activeForColumn(column: ConfirmedColumnKey, filters: ConfirmedFilters, rangeFilter: ExportStatus): boolean {
  if (column === "status") return rangeFilter !== "unexported";
  if (column === "expense_type") return filters.expenseTypes.length > 0;
  if (column === "invoice_category") return filters.categories.length > 0;
  if (column === "vendor_code") return Boolean(filters.vendorCode);
  if (column === "vendor_name") return Boolean(filters.vendorName);
  if (column === "po_number") return Boolean(filters.poNumber);
  if (column === "invoice_number") return Boolean(filters.invoiceNumber);
  if (column === "invoice_date") return Boolean(filters.invoiceDateFrom || filters.invoiceDateTo);
  if (column === "total_amount") return Boolean(filters.amountMin || filters.amountMax);
  return false;
}

function emptyMessage(rangeFilter: ExportStatus, allRows: Invoice[], hasActiveFilters: boolean): string {
  if (!allRows.length) return "No confirmed invoices";
  if (rangeFilter === "unexported") {
    if (hasActiveFilters) return "No unexported invoices match the current filter";
    if (allRows.every(hasExportRecord)) return `No unexported invoices, ${allRows.length} invoicesconfirmed invoiceshave all been exported`;
    return "No unexported invoices";
  }
  if (rangeFilter === "exported") {
    return hasActiveFilters ? "No exported invoices match the current filter" : "No exported invoices";
  }
  return hasActiveFilters ? "No confirmed invoices match the current filter" : "No confirmed invoices";
}

function batchItems(rows: Invoice[], rangeFilter: ExportStatus): RowItem[] {
  if (rangeFilter !== "exported") {
    return rows.map((invoice) => ({ type: "invoice", key: `invoice-${invoice.id}`, invoice }));
  }
  const groups = new Map<string, { exportedAt: string; invoices: Invoice[] }>();
  rows.forEach((invoice) => {
    const batchId = invoice.export_batch_id || "__unknown__";
    if (!groups.has(batchId)) groups.set(batchId, { exportedAt: invoice.exported_at || "", invoices: [] });
    groups.get(batchId)!.invoices.push(invoice);
  });
  return Array.from(groups.entries())
    .sort((left, right) => right[1].exportedAt.localeCompare(left[1].exportedAt))
    .flatMap(([batchId, group]) => [
      {
        type: "batch" as const,
        key: `batch-${batchId}`,
        label: `Exported at ${displayDate(group.exportedAt) || "Unknown time"}`,
        count: group.invoices.length
      },
      ...group.invoices
        .map((invoice) => ({ type: "invoice" as const, key: `invoice-${invoice.id}`, invoice }))
    ]);
}

function rowClass(selected: boolean): string {
  return [
    "group grid min-w-[1232px] items-center border-b border-ink-300/10 px-3 text-sm text-ink-700 transition-colors duration-micro ease-std",
    selected ? "bg-brand-50/80" : "bg-card hover:bg-brand-50"
  ].join(" ");
}

const cellClass = "truncate text-sm font-normal text-ink-700";
const mutedCellClass = "truncate text-sm font-normal text-ink-300";

const ConfirmedInvoiceRow = memo(function ConfirmedInvoiceRow({
  invoice,
  selected,
  onToggle
}: {
  invoice: Invoice;
  selected: boolean;
  onToggle: (id: number) => void;
}) {
  const exported = hasExportRecord(invoice);
  return (
    <div className={rowClass(selected)} style={{ gridTemplateColumns: gridTemplate }}>
      <div>
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggle(invoice.id)}
          aria-label={`Select ${invoice.original_filename}`}
        />
      </div>
      <div className={invoice.expense_type ? cellClass : mutedCellClass}>{invoice.expense_type || "—"}</div>
      <div className={invoice.invoice_category ? cellClass : mutedCellClass}>{invoice.invoice_category || "—"}</div>
      <div className={invoice.vendor_code ? cellClass : mutedCellClass}>{invoice.vendor_code || "—"}</div>
      <div className={invoice.vendor_name ? cellClass : mutedCellClass} title={invoice.vendor_name}>{invoice.vendor_name || "—"}</div>
      <div className={invoice.po_number ? cellClass : mutedCellClass}>{invoice.po_number || "—"}</div>
      <div className={invoice.invoice_number ? cellClass : mutedCellClass}>{invoice.invoice_number || "—"}</div>
      <div className={invoice.invoice_date ? cellClass : mutedCellClass}>{invoice.invoice_date || "—"}</div>
      <div className="truncate text-sm font-normal text-ok-text">{formatAmount(invoice.total_amount)}</div>
      <div className={cellClass}>{exported ? "Exported" : "Unexported"}</div>
      <div>
        <a
          href={fileUrl(invoice.id)}
          target="_blank"
          rel="noreferrer"
          className="rounded-soft px-2 py-1 text-xs font-semibold text-brand-700 opacity-0 transition-opacity duration-micro hover:bg-white group-hover:opacity-100"
        >
          View
        </a>
      </div>
    </div>
  );
});

function BatchSeparator({ label, count }: { label: string; count: number }) {
  return (
    <div className="grid min-w-[1232px] items-center border-b border-brand-500/10 bg-brand-50/70 px-4 text-xs font-semibold text-brand-700" style={{ gridTemplateColumns: gridTemplate }}>
      <div className="col-span-11">{label} · {count} invoices</div>
    </div>
  );
}

export function ConfirmedTable({
  rows,
  allRows,
  categories,
  filters,
  rangeFilter,
  sort,
  selectedIds,
  loading,
  hasActiveFilters,
  onPatchFilters,
  onClearColumn,
  onSort,
  onToggleRow,
  onToggleAll,
  onResetFilters
}: ConfirmedTableProps) {
  const parentRef = useRef<HTMLDivElement | null>(null);
  const expenseOptions = useMemo(() => {
    const configured = expenseTypeOptions.map((option) => ({
      value: option.value || "__empty__",
      label: option.label
    }));
    const discovered = uniqueOptions(allRows.map((row) => row.expense_type)).filter(
      (option) => !configured.some((item) => item.value === option.value)
    );
    return [...configured, ...discovered];
  }, [allRows]);
  const categoryOptions = useMemo(() => {
    return uniqueOptions([...categories, ...allRows.map((row) => row.invoice_category)]);
  }, [allRows, categories]);
  const optionMap = useMemo(() => ({
    expense_type: expenseOptions,
    invoice_category: categoryOptions
  }), [categoryOptions, expenseOptions]);
  const items = useMemo(() => batchItems(rows, rangeFilter), [rangeFilter, rows]);
  const selectedVisible = useMemo(() => rows.filter((row) => selectedIds.has(row.id)).length, [rows, selectedIds]);
  const allVisibleSelected = rows.length > 0 && selectedVisible === rows.length;
  const emptyStateMessage = emptyMessage(rangeFilter, allRows, hasActiveFilters);

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => items[index]?.type === "batch" ? 36 : 52,
    getItemKey: (index) => items[index]?.key || index,
    overscan: 10
  });

  return (
    <section className="overflow-hidden rounded-card border border-ink-300/10 bg-card shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-300/10 px-4 py-3">
        <div className="text-sm font-semibold text-ink-500">
          {rangeFilter === "exported"
            ? `${items.filter((item) => item.type === "batch").length} batches / ${rows.length} invoices`
            : `${rows.length} rows`}
          {selectedVisible ? <span className="ml-2 text-brand-700">Selected {selectedVisible}</span> : null}
        </div>
        <div className="flex gap-2">
          <Button className="min-h-8 px-3 py-1.5" onClick={onToggleAll} disabled={!rows.length}>
            {allVisibleSelected ? "Clear Selection" : "Select All"}
          </Button>
          <Button className="min-h-8 px-3 py-1.5" onClick={onResetFilters} disabled={!hasActiveFilters}>
            Reset Sorting and Filters
          </Button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <div className="min-w-[1232px]">
          <div className="sticky top-0 z-10 grid items-center border-b border-ink-300/15 bg-card px-3 py-2 text-xs font-semibold uppercase tracking-[0.02em] text-ink-500" style={{ gridTemplateColumns: gridTemplate }}>
            <div>
              <input
                type="checkbox"
                checked={allVisibleSelected}
                onChange={onToggleAll}
                disabled={!rows.length}
                aria-label="Select all filtered results"
              />
            </div>
            {columns.map((column) => (
              <ColumnFilter
                key={column.key}
                column={column.key}
                label={column.label}
                filters={filters}
                sort={sort}
                options={optionMap[column.key as keyof typeof optionMap]}
                active={activeForColumn(column.key, filters, rangeFilter)}
                sortable={column.sortable}
                onApply={onPatchFilters}
                onClear={onClearColumn}
                onSort={onSort}
              />
            ))}
            <div />
          </div>

          <div ref={parentRef} className="h-[min(68vh,720px)] overflow-auto">
            {loading ? (
              <div className="grid h-48 place-items-center text-sm font-semibold text-ink-300">Loading confirmed invoices...</div>
            ) : items.length ? (
              <div className="relative" style={{ height: virtualizer.getTotalSize() }}>
                {virtualizer.getVirtualItems().map((virtualRow) => {
                  const item = items[virtualRow.index];
                  return (
                    <div
                      key={virtualRow.key}
                      data-index={virtualRow.index}
                      ref={virtualizer.measureElement}
                      className="absolute left-0 top-0 w-full"
                      style={{ transform: `translateY(${virtualRow.start}px)` }}
                    >
                      {item.type === "batch" ? (
                        <BatchSeparator label={item.label} count={item.count} />
                      ) : (
                        <ConfirmedInvoiceRow invoice={item.invoice} selected={selectedIds.has(item.invoice.id)} onToggle={onToggleRow} />
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="grid h-48 place-items-center text-sm font-semibold text-ink-300">{emptyStateMessage}</div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
