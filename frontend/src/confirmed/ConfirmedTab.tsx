import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "motion/react";
import { getExportStats, listInvoiceCategories, listInvoices } from "../api";
import type { ExportStats, ExportStatus, Invoice } from "../types";
import { Button } from "../ui/Button";
import { SpinnerPanel } from "../ui/Spinner";
import { useToast } from "../shell/ToastHost";
import { storedExportStatus, storeExportStatus } from "../lib/storage";
import { ExportDrawer } from "./ExportDrawer";
import { ExportStatsBar } from "./ExportStatsBar";
import { ConfirmedTable } from "./ConfirmedTable";
import { useConfirmedFilters } from "./useConfirmedFilters";
import type { ConfirmedFilters } from "./useConfirmedFilters";

const emptyStats: ExportStats = {
  confirmed_count: 0,
  exported_count: 0,
  unexported_count: 0
};

const rangeOptions: Array<{ value: ExportStatus; label: string }> = [
  { value: "unexported", label: "Unexported" },
  { value: "exported", label: "Exported" },
  { value: "all", label: "All" }
];

function RangeChips({
  value,
  onChange
}: {
  value: ExportStatus;
  onChange: (value: ExportStatus) => void;
}) {
  return (
    <div className="inline-flex items-center gap-1 rounded-pill bg-ink-300/10 px-1 py-1" role="radiogroup" aria-label="Display range">
      {rangeOptions.map((option) => {
        const active = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option.value)}
            className={[
              "relative min-w-16 rounded-pill px-3 py-1.5 text-sm font-semibold transition-colors duration-fast",
              active ? "text-brand-700" : "text-ink-500 hover:text-ink-900"
            ].join(" ")}
          >
            <span className="relative z-10">{option.label}</span>
            {active ? (
              <motion.span
                layoutId="confirmed-range-underline"
                className="absolute inset-x-3 bottom-1 h-0.5 rounded-pill bg-brand-500"
                transition={{ duration: 0.18, ease: [0.4, 0, 0.2, 1] }}
              />
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

export default function ConfirmedTab() {
  const toast = useToast();
  const [rows, setRows] = useState<Invoice[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [stats, setStats] = useState<ExportStats>(emptyStats);
  const [loading, setLoading] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(() => new Set());

  const {
    filters,
    setColumnFilter,
    clearColumn,
    sortedRows,
    rangeFilter,
    setRangeFilter,
    sort,
    setSort,
    hasActiveFilters,
    resetFilters,
    exportFilters
  } = useConfirmedFilters(rows, storedExportStatus());

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextRows, nextStats, nextCategories] = await Promise.all([
        listInvoices({ status: "confirmed" }),
        getExportStats(),
        listInvoiceCategories()
      ]);
      setRows(nextRows);
      setStats(nextStats);
      setCategories(nextCategories);
      setSelectedIds((current) => new Set([...current].filter((id) => nextRows.some((row) => row.id === id))));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load confirmed invoices");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    storeExportStatus(rangeFilter);
  }, [rangeFilter]);

  const selectedInvoices = useMemo(
    () => sortedRows.filter((invoice) => selectedIds.has(invoice.id)),
    [selectedIds, sortedRows]
  );

  const patchFilters = (patch: Partial<ConfirmedFilters>) => {
    if (patch.expenseTypes !== undefined) setColumnFilter("expenseTypes", patch.expenseTypes);
    if (patch.categories !== undefined) setColumnFilter("categories", patch.categories);
    if (patch.vendorCode !== undefined) setColumnFilter("vendorCode", patch.vendorCode);
    if (patch.vendorName !== undefined) setColumnFilter("vendorName", patch.vendorName);
    if (patch.poNumber !== undefined) setColumnFilter("poNumber", patch.poNumber);
    if (patch.invoiceNumber !== undefined) setColumnFilter("invoiceNumber", patch.invoiceNumber);
    if (patch.invoiceDateFrom !== undefined) setColumnFilter("invoiceDateFrom", patch.invoiceDateFrom);
    if (patch.invoiceDateTo !== undefined) setColumnFilter("invoiceDateTo", patch.invoiceDateTo);
    if (patch.amountMin !== undefined) setColumnFilter("amountMin", patch.amountMin);
    if (patch.amountMax !== undefined) setColumnFilter("amountMax", patch.amountMax);
  };

  const toggleRow = (id: number) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAllVisible = () => {
    setSelectedIds((current) => {
      const allVisibleSelected = sortedRows.length > 0 && sortedRows.every((row) => current.has(row.id));
      if (allVisibleSelected) {
        const next = new Set(current);
        sortedRows.forEach((row) => next.delete(row.id));
        return next;
      }
      const next = new Set(current);
      sortedRows.forEach((row) => next.add(row.id));
      return next;
    });
  };

  const openExport = () => {
    if (!selectedInvoices.length) {
      toast.error("Select invoices to export");
      return;
    }
    setDrawerOpen(true);
  };

  if (loading && !rows.length) {
    return <SpinnerPanel label="Loading confirmed invoices" />;
  }

  return (
    <div className="grid gap-4">
      <section className="rounded-card border border-ink-300/10 bg-card px-4 py-3 shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
            <ExportStatsBar stats={stats} />
            <span className="text-sm font-semibold text-ink-300">
              Selected {selectedInvoices.length}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <RangeChips value={rangeFilter} onChange={setRangeFilter} />
            <Button variant="primary" onClick={openExport} disabled={!selectedInvoices.length}>
              Export{selectedInvoices.length ? ` (${selectedInvoices.length})` : ""}
            </Button>
          </div>
        </div>
      </section>

      <ConfirmedTable
        rows={sortedRows}
        allRows={rows}
        categories={categories}
        filters={filters}
        rangeFilter={rangeFilter}
        sort={sort}
        selectedIds={selectedIds}
        loading={loading}
        hasActiveFilters={hasActiveFilters}
        onPatchFilters={patchFilters}
        onClearColumn={clearColumn}
        onSort={setSort}
        onToggleRow={toggleRow}
        onToggleAll={toggleAllVisible}
        onResetFilters={resetFilters}
      />

      <ExportDrawer
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        invoices={selectedInvoices}
        exportFilters={exportFilters}
        onExported={refresh}
        onClearSelection={() => setSelectedIds(new Set())}
      />
    </div>
  );
}
