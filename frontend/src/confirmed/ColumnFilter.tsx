import { useEffect, useMemo, useState } from "react";
import { Popover, PopoverClose } from "../ui/Popover";
import { Button } from "../ui/Button";
import { SelectInput, TextInput } from "../ui/Field";
import type { ConfirmedColumnKey, ConfirmedFilters, ConfirmedSort, ConfirmedSortKey } from "./useConfirmedFilters";

type FilterOption = {
  value: string;
  label: string;
};

type ColumnFilterProps = {
  column: ConfirmedColumnKey;
  label: string;
  filters: ConfirmedFilters;
  sort: ConfirmedSort;
  options?: FilterOption[];
  active: boolean;
  sortable?: boolean;
  onApply: (patch: Partial<ConfirmedFilters>) => void;
  onClear: (column: ConfirmedColumnKey) => void;
  onSort: (sort: ConfirmedSort) => void;
};

const textColumns: Partial<Record<ConfirmedColumnKey, keyof ConfirmedFilters>> = {
  vendor_code: "vendorCode",
  vendor_name: "vendorName",
  po_number: "poNumber",
  invoice_number: "invoiceNumber"
};

function arrayToggle(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

export function ColumnFilter({
  column,
  label,
  filters,
  sort,
  options = [],
  active,
  sortable = true,
  onApply,
  onClear,
  onSort
}: ColumnFilterProps) {
  const textKey = textColumns[column];
  const [textValue, setTextValue] = useState(textKey ? String(filters[textKey]) : "");
  const [expenseTypes, setExpenseTypes] = useState(filters.expenseTypes);
  const [categories, setCategories] = useState(filters.categories);
  const [dateFrom, setDateFrom] = useState(filters.invoiceDateFrom);
  const [dateTo, setDateTo] = useState(filters.invoiceDateTo);
  const [amountMin, setAmountMin] = useState(filters.amountMin);
  const [amountMax, setAmountMax] = useState(filters.amountMax);

  useEffect(() => {
    if (textKey) setTextValue(String(filters[textKey]));
    setExpenseTypes(filters.expenseTypes);
    setCategories(filters.categories);
    setDateFrom(filters.invoiceDateFrom);
    setDateTo(filters.invoiceDateTo);
    setAmountMin(filters.amountMin);
    setAmountMax(filters.amountMax);
  }, [filters, textKey]);

  const sortButtons = sortable && column !== "status" ? (
    <div className="grid grid-cols-2 gap-2">
      <Button
        className="min-h-8 px-2 py-1 text-xs"
        variant={sort.key === column && sort.direction === "asc" ? "primary" : "ghost"}
        onClick={() => onSort({ key: column as ConfirmedSortKey, direction: "asc" })}
      >
        Ascending
      </Button>
      <Button
        className="min-h-8 px-2 py-1 text-xs"
        variant={sort.key === column && sort.direction === "desc" ? "primary" : "ghost"}
        onClick={() => onSort({ key: column as ConfirmedSortKey, direction: "desc" })}
      >
        Descending
      </Button>
    </div>
  ) : null;

  const body = useMemo(() => {
    if (textKey) {
      return <TextInput value={textValue} onChange={(event) => setTextValue(event.target.value)} placeholder={`Search ${label}`} />;
    }
    if (column === "expense_type" || column === "invoice_category") {
      const selected = column === "expense_type" ? expenseTypes : categories;
      const setSelected = column === "expense_type" ? setExpenseTypes : setCategories;
      return (
        <div className="flex max-h-44 flex-wrap gap-2 overflow-auto">
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => setSelected(arrayToggle(selected, option.value))}
              className={[
                "rounded-pill px-2.5 py-1 text-xs font-semibold transition-colors duration-micro",
                selected.includes(option.value) ? "bg-brand-500 text-white" : "bg-ink-300/10 text-ink-500 hover:bg-brand-50 hover:text-brand-700"
              ].join(" ")}
            >
              {option.label}
            </button>
          ))}
          {!options.length ? <span className="text-sm text-ink-300">No options</span> : null}
        </div>
      );
    }
    if (column === "invoice_date") {
      return (
        <div className="grid gap-2">
          <TextInput type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} aria-label="Invoice date start" />
          <TextInput type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} aria-label="Invoice date end" />
        </div>
      );
    }
    if (column === "total_amount") {
      return (
        <div className="grid gap-2">
          <TextInput inputMode="decimal" value={amountMin} onChange={(event) => setAmountMin(event.target.value.replace(/[^\d.]/g, ""))} placeholder="Minimum amount" />
          <TextInput inputMode="decimal" value={amountMax} onChange={(event) => setAmountMax(event.target.value.replace(/[^\d.]/g, ""))} placeholder="Maximum amount" />
        </div>
      );
    }
    if (column === "status") {
      return <SelectInput disabled value="" aria-label="Status filter"><option>Use the top display range selector</option></SelectInput>;
    }
    return <span className="text-sm text-ink-300">No filter is available for this column</span>;
  }, [amountMax, amountMin, categories, column, dateFrom, dateTo, expenseTypes, label, options, textKey, textValue]);

  const apply = () => {
    if (textKey) onApply({ [textKey]: textValue } as Partial<ConfirmedFilters>);
    if (column === "expense_type") onApply({ expenseTypes });
    if (column === "invoice_category") onApply({ categories });
    if (column === "invoice_date") onApply({ invoiceDateFrom: dateFrom, invoiceDateTo: dateTo });
    if (column === "total_amount") onApply({ amountMin, amountMax });
  };

  return (
    <Popover
      align="start"
      trigger={(
        <button type="button" className="group inline-flex items-center gap-1 rounded-soft px-1.5 py-1 text-left hover:bg-brand-50">
          <span>{label}</span>
          {sort.key === column ? <span className="text-brand-600">{sort.direction === "asc" ? "↑" : "↓"}</span> : null}
          <span className={["size-1.5 rounded-pill", active ? "bg-brand-500" : "bg-transparent group-hover:bg-ink-300"].join(" ")} />
        </button>
      )}
    >
      <div className="grid gap-3">
        <div className="text-xs font-semibold uppercase tracking-[0.04em] text-ink-300">{label}</div>
        {sortButtons}
        {body}
        <div className="flex justify-end gap-2">
          <Button className="min-h-8 px-2 py-1 text-xs" onClick={() => onClear(column)} disabled={!active}>Clear</Button>
          <PopoverClose asChild>
            <Button className="min-h-8 px-2 py-1 text-xs" variant="primary" onClick={apply}>Apply</Button>
          </PopoverClose>
        </div>
      </div>
    </Popover>
  );
}
