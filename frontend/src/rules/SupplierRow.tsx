import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { memo } from "react";
import type { Scheme, Supplier } from "../types";

type Props = {
  supplier: Supplier;
  assignedScheme: string;
  schemes: Scheme[];
  disabled: boolean;
  hasAutoArchive: boolean;
  onAssign: (schemeName: string) => void;
  onClear: () => void;
  onDelete: () => void;
  onCreateNewScheme: () => void;
  onEditScheme: () => void;
};

export const SupplierRow = memo(function SupplierRow({
  supplier,
  assignedScheme,
  schemes,
  disabled,
  hasAutoArchive,
  onAssign,
  onClear,
  onDelete,
  onCreateNewScheme,
  onEditScheme
}: Props) {
  const isDefault = !assignedScheme || assignedScheme === "default";
  const label = assignedScheme || "default";

  const schemeBtn = [
    "inline-flex w-28 items-center justify-between gap-1 rounded-pill px-2.5 py-1 text-xs font-semibold leading-5",
    "transition-colors disabled:pointer-events-none disabled:opacity-50",
    isDefault
      ? "bg-ink-300/10 text-ink-500 hover:bg-ink-300/20"
      : "bg-ok-bg text-ok-text hover:brightness-95"
  ].join(" ");

  return (
    <div className="flex min-h-14 items-center gap-2 border-b border-ink-300/10 px-3 py-2 text-sm">
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium text-ink-900">{supplier.name}</div>
        <div className="text-xs text-ink-500">{supplier.code}</div>
      </div>

      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button type="button" disabled={disabled} className={schemeBtn}>
            → {label}
            <span className="text-[9px] opacity-50">▾</span>
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content
            sideOffset={4}
            align="end"
            className="z-50 min-w-[220px] rounded-card border border-ink-300/15 bg-white p-1 text-sm shadow-cardH"
          >
            <DropdownMenu.Item
              onSelect={onCreateNewScheme}
              className="cursor-pointer rounded-soft px-3 py-2 outline-none data-[highlighted]:bg-brand-50"
            >
              + New Scheme (inherit from...)
            </DropdownMenu.Item>
            {!isDefault && (
              <>
                <DropdownMenu.Separator className="my-1 h-px bg-ink-300/10" />
                <DropdownMenu.Item
                  onSelect={onClear}
                  className="cursor-pointer rounded-soft px-3 py-2 text-ink-500 outline-none data-[highlighted]:bg-brand-50"
                >
                  Restore to default
                </DropdownMenu.Item>
              </>
            )}
            <DropdownMenu.Separator className="my-1 h-px bg-ink-300/10" />
            <div className="px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-ink-400">Assign Scheme</div>
            <DropdownMenu.Item
              onSelect={() => onAssign("default")}
              className="cursor-pointer rounded-soft px-3 py-2 outline-none data-[highlighted]:bg-brand-50"
            >
              default{label === "default" ? " ✓" : ""}
            </DropdownMenu.Item>
            {schemes.filter((scheme) => scheme.name !== "default").map((scheme) => (
              <DropdownMenu.Item
                key={scheme.name}
                onSelect={() => onAssign(scheme.name)}
                className="cursor-pointer rounded-soft px-3 py-2 outline-none data-[highlighted]:bg-brand-50"
              >
                {scheme.name}{scheme.name === label ? " ✓" : ""}
              </DropdownMenu.Item>
            ))}
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>

      <button
        type="button"
        disabled={disabled}
        onClick={onEditScheme}
        className={[
          "inline-flex w-[88px] items-center justify-between gap-1 rounded-pill px-2.5 py-1 text-xs font-semibold leading-5",
          "transition-colors disabled:pointer-events-none disabled:opacity-50",
          hasAutoArchive
            ? "bg-brand-50 text-brand-700 hover:bg-brand-100"
            : "bg-ink-300/10 text-ink-400 hover:bg-ink-300/20"
        ].join(" ")}
      >
        Auto-Archive
        <span className="text-[9px] opacity-50">▾</span>
      </button>

      <button
        type="button"
        disabled={disabled}
        onClick={onDelete}
        aria-label="Delete Supplier"
        title="Delete Supplier"
        className="grid size-8 place-items-center rounded-soft text-ink-400 outline-none transition-[transform,background,color] duration-micro ease-std hover:bg-danger-bg hover:text-danger-text active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50"
      >
        ×
      </button>
    </div>
  );
});
