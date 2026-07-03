import { useMemo, useState } from "react";
import type { ExportMode, ExportStatus, Invoice } from "../types";
import { useDebounce } from "../lib/hooks";

export type ConfirmedSortKey =
  | "expense_type"
  | "invoice_category"
  | "vendor_code"
  | "vendor_name"
  | "po_number"
  | "invoice_number"
  | "invoice_date"
  | "total_amount"
  | "original_filename";

export type ConfirmedColumnKey = ConfirmedSortKey | "status";

export type ConfirmedSort = {
  key: ConfirmedSortKey;
  direction: "asc" | "desc";
};

export type ConfirmedFilters = {
  expenseTypes: string[];
  categories: string[];
  vendorCode: string;
  vendorName: string;
  poNumber: string;
  invoiceNumber: string;
  invoiceDateFrom: string;
  invoiceDateTo: string;
  amountMin: string;
  amountMax: string;
};

export type ConfirmedTextFilterKey = "vendorCode" | "vendorName" | "poNumber" | "invoiceNumber";

export type ExportArchiveFilters = {
  mode: ExportMode;
  export_status: ExportStatus;
  day?: string;
  date_from?: string;
  date_to?: string;
  supplier?: string;
  category?: string;
};

export const emptyConfirmedFilters: ConfirmedFilters = {
  expenseTypes: [],
  categories: [],
  vendorCode: "",
  vendorName: "",
  poNumber: "",
  invoiceNumber: "",
  invoiceDateFrom: "",
  invoiceDateTo: "",
  amountMin: "",
  amountMax: ""
};

const defaultConfirmedSort: ConfirmedSort = { key: "vendor_name", direction: "asc" };
const defaultAllSort: ConfirmedSort = { key: "invoice_date", direction: "desc" };
const sortCollator = new Intl.Collator(["zh-Hans-CN", "en-US"], { numeric: true, sensitivity: "base" });

export function hasExportRecord(invoice: Invoice): boolean {
  return Boolean(invoice.archive_number || invoice.exported_filename || invoice.exported_path || invoice.export_batch_id);
}

function includesText(value: string, needle: string): boolean {
  return !needle.trim() || value.toLowerCase().includes(needle.trim().toLowerCase());
}

function numericFilterValue(value: string): number | null {
  if (!value.trim()) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function confirmedSortValue(invoice: Invoice, key: ConfirmedSortKey): string | number {
  if (key === "total_amount") return Number(invoice.total_amount || 0);
  if (key === "invoice_date") {
    const parsed = Date.parse(invoice.invoice_date_iso || invoice.invoice_date || "");
    return Number.isNaN(parsed) ? invoice.invoice_date || "" : parsed;
  }
  return String(invoice[key] ?? "").trim();
}

export function compareConfirmedInvoices(a: Invoice, b: Invoice, sort: ConfirmedSort): number {
  const left = confirmedSortValue(a, sort.key);
  const right = confirmedSortValue(b, sort.key);
  const result = typeof left === "number" && typeof right === "number"
    ? left - right
    : sortCollator.compare(String(left), String(right));
  if (result !== 0) return sort.direction === "asc" ? result : -result;
  return sortCollator.compare(a.vendor_name || "", b.vendor_name || "") || a.id - b.id;
}

function matchesFilters(invoice: Invoice, filters: ConfirmedFilters, rangeFilter: ExportStatus): boolean {
  if (rangeFilter === "exported" && !hasExportRecord(invoice)) return false;
  if (rangeFilter === "unexported" && hasExportRecord(invoice)) return false;
  if (filters.expenseTypes.length) {
    const value = invoice.expense_type || "__empty__";
    if (!filters.expenseTypes.includes(value)) return false;
  }
  if (filters.categories.length && !filters.categories.includes(invoice.invoice_category || "__empty__")) return false;
  if (!includesText(invoice.vendor_code || "", filters.vendorCode)) return false;
  if (!includesText(invoice.vendor_name || "", filters.vendorName)) return false;
  if (!includesText(invoice.po_number || "", filters.poNumber)) return false;
  if (!includesText(invoice.invoice_number || "", filters.invoiceNumber)) return false;
  const invoiceDate = invoice.invoice_date_iso || invoice.invoice_date || "";
  if (filters.invoiceDateFrom && invoiceDate < filters.invoiceDateFrom) return false;
  if (filters.invoiceDateTo && invoiceDate > filters.invoiceDateTo) return false;
  const amount = Number(invoice.total_amount || 0);
  const min = numericFilterValue(filters.amountMin);
  const max = numericFilterValue(filters.amountMax);
  if (min !== null && amount < min) return false;
  if (max !== null && amount > max) return false;
  return true;
}

function sortForRange(rangeFilter: ExportStatus): ConfirmedSort {
  return rangeFilter === "all" ? defaultAllSort : defaultConfirmedSort;
}

export function exportFiltersFor(filters: ConfirmedFilters, rangeFilter: ExportStatus): ExportArchiveFilters {
  const supplier = filters.vendorName.trim() || filters.vendorCode.trim();
  if (supplier) return { mode: "supplier", export_status: rangeFilter, supplier };
  const category = filters.categories.length === 1 && filters.categories[0] !== "__empty__" ? filters.categories[0] : "";
  if (category) return { mode: "category", export_status: rangeFilter, category };
  if (filters.invoiceDateFrom || filters.invoiceDateTo) {
    return {
      mode: "range",
      export_status: rangeFilter,
      date_from: filters.invoiceDateFrom || undefined,
      date_to: filters.invoiceDateTo || undefined
    };
  }
  return { mode: "all", export_status: rangeFilter };
}

export function useConfirmedFilters(rows: Invoice[], initialRangeFilter: ExportStatus) {
  const [filters, setFilters] = useState<ConfirmedFilters>(emptyConfirmedFilters);
  const [rangeFilter, setRangeFilterState] = useState<ExportStatus>(initialRangeFilter);
  const [sort, setSort] = useState<ConfirmedSort>(() => sortForRange(initialRangeFilter));

  const debouncedVendorCode = useDebounce(filters.vendorCode, 180);
  const debouncedVendorName = useDebounce(filters.vendorName, 180);
  const debouncedPoNumber = useDebounce(filters.poNumber, 180);
  const debouncedInvoiceNumber = useDebounce(filters.invoiceNumber, 180);

  const debouncedFilters = useMemo<ConfirmedFilters>(() => ({
    ...filters,
    vendorCode: debouncedVendorCode,
    vendorName: debouncedVendorName,
    poNumber: debouncedPoNumber,
    invoiceNumber: debouncedInvoiceNumber
  }), [debouncedInvoiceNumber, debouncedPoNumber, debouncedVendorCode, debouncedVendorName, filters]);

  const setColumnFilter = <K extends keyof ConfirmedFilters>(key: K, value: ConfirmedFilters[K]) => {
    setFilters((current) => ({ ...current, [key]: value }));
  };

  const clearColumn = (column: ConfirmedColumnKey) => {
    if (column === "status") {
      setRangeFilter("unexported");
      return;
    }
    if (column === "expense_type") setColumnFilter("expenseTypes", []);
    if (column === "invoice_category") setColumnFilter("categories", []);
    if (column === "vendor_code") setColumnFilter("vendorCode", "");
    if (column === "vendor_name") setColumnFilter("vendorName", "");
    if (column === "po_number") setColumnFilter("poNumber", "");
    if (column === "invoice_number") setColumnFilter("invoiceNumber", "");
    if (column === "invoice_date") setFilters((current) => ({ ...current, invoiceDateFrom: "", invoiceDateTo: "" }));
    if (column === "total_amount") setFilters((current) => ({ ...current, amountMin: "", amountMax: "" }));
  };

  const setRangeFilter = (value: ExportStatus) => {
    setRangeFilterState(value);
    setSort(sortForRange(value));
  };

  const sortedRows = useMemo(() => {
    return rows
      .filter((invoice) => matchesFilters(invoice, debouncedFilters, rangeFilter))
      .sort((left, right) => compareConfirmedInvoices(left, right, sort));
  }, [debouncedFilters, rangeFilter, rows, sort]);

  const hasActiveFilters = useMemo(() => {
    return rangeFilter !== "unexported"
      || filters.expenseTypes.length > 0
      || filters.categories.length > 0
      || Boolean(filters.vendorCode || filters.vendorName || filters.poNumber || filters.invoiceNumber)
      || Boolean(filters.invoiceDateFrom || filters.invoiceDateTo || filters.amountMin || filters.amountMax)
      || sort.key !== sortForRange(rangeFilter).key
      || sort.direction !== sortForRange(rangeFilter).direction;
  }, [filters, rangeFilter, sort]);

  const resetFilters = () => {
    setFilters(emptyConfirmedFilters);
    setSort(sortForRange(rangeFilter));
  };

  return {
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
    exportFilters: exportFiltersFor(debouncedFilters, rangeFilter)
  };
}
