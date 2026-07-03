import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useMemo, useRef, useState } from "react";
import { useDebounce } from "../lib/hooks";
import type { Scheme, Supplier } from "../types";
import { Button } from "../ui/Button";
import { SupplierRow } from "./SupplierRow";

type ArchiveFilter = "all" | "active" | "inactive";

type Props = {
  suppliers: Supplier[];
  map: Record<string, string>;
  schemes: Scheme[];
  disabled: boolean;
  autoArchiveActive: Set<string>;
  onAssign: (code: string, schemeName: string) => void;
  onClear: (code: string) => void;
  onDelete: (supplier: Supplier) => void;
  onCreateNewSchemeFor: (supplier: Supplier) => void;
  onEditSchemeFor: (supplier: Supplier) => void;
  onAddSupplier: () => void;
};

function ColumnFilter({
  label,
  active,
  width,
  children
}: {
  label: string;
  active: boolean;
  width: string;
  children: React.ReactNode;
}) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className={[
            "inline-flex items-center justify-between gap-1 rounded-soft px-2 py-1 text-xs font-semibold outline-none",
            "transition-colors focus-visible:ring-2 focus-visible:ring-brand-500",
            width,
            active
              ? "text-brand-700 bg-brand-50 hover:bg-brand-100"
              : "text-ink-500 hover:bg-ink-300/10 hover:text-ink-700"
          ].join(" ")}
        >
          {label}
          <span className="text-[9px] opacity-50">▾</span>
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          sideOffset={4}
          align="end"
          className="z-50 min-w-[160px] rounded-card border border-ink-300/15 bg-white p-1 text-sm shadow-cardH"
        >
          {children}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

function FilterItem({
  checked,
  onSelect,
  children
}: {
  checked: boolean;
  onSelect: () => void;
  children: React.ReactNode;
}) {
  return (
    <DropdownMenu.Item
      onSelect={onSelect}
      className="flex cursor-pointer items-center justify-between rounded-soft px-3 py-2 outline-none data-[highlighted]:bg-brand-50"
    >
      {children}
      {checked && <span className="text-brand-500">✓</span>}
    </DropdownMenu.Item>
  );
}

export function SupplierListPanel({
  suppliers,
  map,
  schemes,
  disabled,
  autoArchiveActive,
  onAssign,
  onClear,
  onDelete,
  onCreateNewSchemeFor,
  onEditSchemeFor,
  onAddSupplier
}: Props) {
  const [query, setQuery] = useState("");
  const [schemeFilter, setSchemeFilter] = useState<string>("all");
  const [archiveFilter, setArchiveFilter] = useState<ArchiveFilter>("all");
  const debounced = useDebounce(query, 150).toLowerCase();

  const filtered = useMemo(() => suppliers.filter((supplier) => {
    if (debounced) {
      const haystack = `${supplier.code} ${supplier.name}`.toLowerCase();
      if (!haystack.includes(debounced)) return false;
    }
    const assignedScheme = map[supplier.code] || "default";
    if (schemeFilter !== "all" && assignedScheme !== schemeFilter) return false;
    if (archiveFilter === "active" && !autoArchiveActive.has(supplier.code)) return false;
    if (archiveFilter === "inactive" && autoArchiveActive.has(supplier.code)) return false;
    return true;
  }), [debounced, schemeFilter, archiveFilter, map, suppliers, autoArchiveActive]);

  const parentRef = useRef<HTMLDivElement | null>(null);
  const virtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 56,
    overscan: 10
  });

  const schemeFilterActive = schemeFilter !== "all";
  const archiveFilterActive = archiveFilter !== "all";

  const schemeFilterLabel = schemeFilter === "all" ? "Scheme" : schemeFilter;
  const archiveFilterLabel = archiveFilter === "all" ? "Auto-Archive"
    : archiveFilter === "active" ? "Active" : "Not Configured";

  const namedSchemes = schemes.filter((s) => !s.is_default);

  return (
    <section className="flex h-[640px] min-w-0 flex-1 flex-col rounded-card border border-ink-300/10 bg-card shadow-card">
      {/* Top bar: search + add */}
      <div className="flex items-center gap-2 border-b border-ink-300/10 p-3">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search code or name..."
          className="min-w-0 flex-1 rounded-soft border border-ink-300/30 px-3 py-2 text-sm outline-none focus:border-brand-500"
        />
        <Button variant="primary" className="shrink-0 min-h-9 px-3 py-1.5 text-sm" onClick={onAddSupplier} disabled={disabled}>
          + Add Supplier
        </Button>
      </div>

      {/* Column header */}
      <div className="flex items-center gap-2 border-b border-ink-300/10 px-3 py-1.5">
        <div className="min-w-0 flex-1">
          <span className="text-xs font-semibold text-ink-500">Supplier</span>
          <span className="ml-1.5 rounded-pill bg-ink-300/10 px-1.5 py-0.5 text-[11px] font-semibold text-ink-400">
            {filtered.length}/{suppliers.length}
          </span>
        </div>
        <ColumnFilter label={schemeFilterLabel} active={schemeFilterActive} width="w-28">
          <FilterItem checked={schemeFilter === "all"} onSelect={() => setSchemeFilter("all")}>All</FilterItem>
          <FilterItem checked={schemeFilter === "default"} onSelect={() => setSchemeFilter("default")}>default</FilterItem>
          {namedSchemes.length > 0 && (
            <>
              <DropdownMenu.Separator className="my-1 h-px bg-ink-300/10" />
              {namedSchemes.map((s) => (
                <FilterItem key={s.name} checked={schemeFilter === s.name} onSelect={() => setSchemeFilter(s.name)}>
                  {s.name}
                </FilterItem>
              ))}
            </>
          )}
        </ColumnFilter>
        <ColumnFilter label={archiveFilterLabel} active={archiveFilterActive} width="w-[88px]">
          <FilterItem checked={archiveFilter === "all"} onSelect={() => setArchiveFilter("all")}>All</FilterItem>
          <FilterItem checked={archiveFilter === "active"} onSelect={() => setArchiveFilter("active")}>Active</FilterItem>
          <FilterItem checked={archiveFilter === "inactive"} onSelect={() => setArchiveFilter("inactive")}>Not Configured</FilterItem>
        </ColumnFilter>
        <div className="w-8 shrink-0" />
      </div>

      {/* Rows */}
      <div ref={parentRef} className="min-h-0 flex-1 overflow-auto">
        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualizer.getVirtualItems().map((item) => {
            const supplier = filtered[item.index];
            return (
              <div
                key={supplier.code}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  right: 0,
                  transform: `translateY(${item.start}px)`
                }}
              >
                <SupplierRow
                  supplier={supplier}
                  assignedScheme={map[supplier.code] ?? ""}
                  schemes={schemes}
                  disabled={disabled}
                  hasAutoArchive={autoArchiveActive.has(supplier.code)}
                  onAssign={(schemeName) => onAssign(supplier.code, schemeName)}
                  onClear={() => onClear(supplier.code)}
                  onDelete={() => onDelete(supplier)}
                  onCreateNewScheme={() => onCreateNewSchemeFor(supplier)}
                  onEditScheme={() => onEditSchemeFor(supplier)}
                />
              </div>
            );
          })}
        </div>
        {!filtered.length ? (
          <div className="grid h-full place-items-center text-sm text-ink-500">No matches</div>
        ) : null}
      </div>
    </section>
  );
}
