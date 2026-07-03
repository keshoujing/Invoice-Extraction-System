import { AnimatePresence, motion } from "motion/react";
import { memo, useEffect, useMemo, useState } from "react";
import { childKeysForArrayField } from "../lib/invoice";
import { formatAmount } from "../lib/format";
import { Button } from "../ui/Button";
import { Field, TextInput } from "../ui/Field";
import type { PromptFieldConfig } from "../types";

type ArrayFieldProps = {
  field: PromptFieldConfig;
  rows: Record<string, unknown>[];
  disabled?: boolean;
  onChange: (rows: Record<string, unknown>[]) => void;
};

type RowProps = {
  row: Record<string, unknown>;
  index: number;
  keys: string[];
  expanded: boolean;
  disabled?: boolean;
  onToggle: () => void;
  onCommit: (index: number, row: Record<string, unknown>) => void;
  onRemove: (index: number) => void;
};

function recordValue(record: Record<string, unknown>, keys: string[]) {
  const wanted = keys.map((key) => key.toLowerCase());
  const found = Object.entries(record).find(([key]) => wanted.includes(key.toLowerCase()));
  return found?.[1];
}

function recordText(record: Record<string, unknown>, keys: string[], fallback = "—") {
  const value = recordValue(record, keys);
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function recordNumber(record: Record<string, unknown>, keys: string[]) {
  const value = recordValue(record, keys);
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  const numeric = Number(String(value ?? "").replace(/[$,\s]/g, ""));
  return Number.isFinite(numeric) ? numeric : 0;
}

function emptyRow(keys: string[]): Record<string, unknown> {
  const usefulKeys = keys.length ? keys : ["description", "quantity", "amount"];
  return Object.fromEntries(usefulKeys.map((key) => [key, ""]));
}

const ArrayFieldRow = memo(function ArrayFieldRow({
  row,
  index,
  keys,
  expanded,
  disabled = false,
  onToggle,
  onCommit,
  onRemove
}: RowProps) {
  const [localRow, setLocalRow] = useState<Record<string, string>>(() => (
    Object.fromEntries(keys.map((key) => [key, String(row[key] ?? "")]))
  ));

  useEffect(() => {
    setLocalRow(Object.fromEntries(keys.map((key) => [key, String(row[key] ?? "")])));
  }, [keys, row]);

  const bol = recordText(row, ["BOL_number", "bol", "bol_number", "BOL"], `#${index + 1}`);
  const name = recordText(row, ["material_name", "material", "description", "name"], "Unnamed Item");
  const amount = recordNumber(row, ["commodity_amount", "amount", "line_amount", "total"]);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -6 }}
      transition={{ duration: 0.18, ease: [0.4, 0, 0.2, 1] }}
      className="overflow-hidden rounded-soft border border-ink-300/15 bg-white"
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left transition-colors duration-fast ease-std hover:bg-brand-50/70"
      >
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold text-ink-900">{bol} · {name}</span>
          <span className="text-xs text-ink-500">Click to expand and edit</span>
        </span>
        <span className="shrink-0 font-mono text-sm font-semibold text-ink-700">{formatAmount(amount)}</span>
      </button>
      {expanded ? (
        <div className="grid gap-3 border-t border-ink-300/10 p-3">
          <div className="grid grid-cols-2 gap-3">
            {keys.map((key) => (
              <Field key={key} label={key}>
                <TextInput
                  value={localRow[key] || ""}
                  disabled={disabled}
                  onChange={(event) => setLocalRow((current) => ({ ...current, [key]: event.target.value }))}
                  onBlur={() => onCommit(index, { ...row, ...localRow })}
                />
              </Field>
            ))}
          </div>
          <div className="flex justify-end">
            <Button variant="danger" className="min-h-8 px-2.5 py-1 text-xs" disabled={disabled} onClick={() => onRemove(index)}>
              Remove Item
            </Button>
          </div>
        </div>
      ) : null}
    </motion.div>
  );
});

export const ArrayField = memo(function ArrayField({ field, rows, disabled = false, onChange }: ArrayFieldProps) {
  const [expandedRows, setExpandedRows] = useState<Set<number>>(() => new Set());
  const keys = useMemo(() => childKeysForArrayField(rows, field), [field, rows]);
  const total = useMemo(
    () => rows.reduce((sum, row) => sum + recordNumber(row, ["commodity_amount", "amount", "line_amount", "total"]), 0),
    [rows]
  );

  function toggleRow(index: number) {
    setExpandedRows((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  function commitRow(index: number, row: Record<string, unknown>) {
    onChange(rows.map((current, currentIndex) => (currentIndex === index ? row : current)));
  }

  function addRow() {
    const nextIndex = rows.length;
    onChange([...rows, emptyRow(keys)]);
    setExpandedRows((current) => new Set([...current, nextIndex]));
  }

  function removeRow(index: number) {
    onChange(rows.filter((_, currentIndex) => currentIndex !== index));
    setExpandedRows((current) => {
      const next = new Set<number>();
      current.forEach((rowIndex) => {
        if (rowIndex < index) next.add(rowIndex);
        if (rowIndex > index) next.add(rowIndex - 1);
      });
      return next;
    });
  }

  return (
    <section className="rounded-card border border-ink-300/10 bg-white p-4 shadow-card">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink-900">{field.key === "line_items" ? "Line Items" : field.key}</h3>
          <p className="text-xs text-ink-500">{rows.length} items · Total {formatAmount(total)}</p>
        </div>
        <Button variant="ghost" className="min-h-8 px-2.5 py-1 text-xs" disabled={disabled} onClick={addRow}>
          Add
        </Button>
      </div>
      <div className="space-y-2">
        <AnimatePresence initial={false}>
          {rows.map((row, index) => (
            <ArrayFieldRow
              key={`${index}-${recordText(row, ["BOL_number", "bol", "description"], "row")}`}
              row={row}
              index={index}
              keys={keys}
              expanded={expandedRows.has(index)}
              disabled={disabled}
              onToggle={() => toggleRow(index)}
              onCommit={commitRow}
              onRemove={removeRow}
            />
          ))}
        </AnimatePresence>
      </div>
    </section>
  );
});
