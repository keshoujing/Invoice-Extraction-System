import { useMemo, useState } from "react";
import type { DragEvent } from "react";
import type { PromptFieldConfig, PromptTagExportColumn, PromptTagExportSettings } from "../types";
import { Button } from "../ui/Button";
import { Badge } from "../ui/Badge";
import {
  defaultExportColumnsForFields,
  exportColumnsForFields,
  exportLabelForKey,
  normalizeExportColumn
} from "../lib/prompt";

type ExportColumnsEditorProps = {
  fields: PromptFieldConfig[];
  settings: PromptTagExportSettings;
  disabled?: boolean;
  onChange: (settings: PromptTagExportSettings) => void;
};

export default function ExportColumnsEditor({
  fields,
  settings,
  disabled = false,
  onChange
}: ExportColumnsEditorProps) {
  const [draggingKey, setDraggingKey] = useState("");
  const visibleColumns = useMemo(
    () => exportColumnsForFields(fields, settings),
    [fields, settings]
  );
  const enabledCount = visibleColumns.filter((column) => column.enabled).length;

  function updateColumns(updater: (columns: PromptTagExportColumn[]) => PromptTagExportColumn[]) {
    const base = exportColumnsForFields(fields, settings);
    onChange({
      custom: true,
      columns: updater(base.map(normalizeExportColumn)).map(normalizeExportColumn)
    });
  }

  function changeColumn(key: string, patch: Partial<PromptTagExportColumn>) {
    updateColumns((columns) => columns.map((column) => (
      column.key === key ? { ...column, ...patch } : column
    )));
  }

  function useDefault() {
    setDraggingKey("");
    onChange({ custom: false, columns: [] });
  }

  function customize() {
    if (settings.custom) return;
    onChange({ custom: true, columns: defaultExportColumnsForFields(fields) });
  }

  function resetColumns() {
    setDraggingKey("");
    onChange({ custom: true, columns: defaultExportColumnsForFields(fields) });
  }

  function moveColumn(sourceKey: string, targetKey: string) {
    if (!sourceKey || !targetKey || sourceKey === targetKey) return;
    updateColumns((columns) => {
      const next = [...columns];
      const sourceIndex = next.findIndex((column) => column.key === sourceKey);
      const targetIndex = next.findIndex((column) => column.key === targetKey);
      if (sourceIndex < 0 || targetIndex < 0) return columns;
      const [moved] = next.splice(sourceIndex, 1);
      next.splice(sourceIndex < targetIndex ? targetIndex - 1 : targetIndex, 0, moved);
      return next;
    });
  }

  function handleDragStart(key: string, event: DragEvent<HTMLButtonElement>) {
    customize();
    setDraggingKey(key);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", key);
  }

  function handleDrop(key: string, event: DragEvent<HTMLTableRowElement>) {
    event.preventDefault();
    moveColumn(draggingKey || event.dataTransfer.getData("text/plain"), key);
    setDraggingKey("");
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink-900">Export Columns</h3>
          <p className="text-xs text-ink-500">
            {settings.custom ? "Custom export columns" : "Default export all fields"} · {enabledCount} / {visibleColumns.length} columns enabled
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={customize} disabled={disabled || settings.custom}>Customize</Button>
          <Button onClick={resetColumns} disabled={disabled}>Reset Columns</Button>
          <Button onClick={useDefault} disabled={disabled || !settings.custom}>Use Default</Button>
        </div>
      </div>

      <div className="overflow-auto rounded-card border border-ink-300/10">
        <table className="min-w-[860px] w-full divide-y divide-ink-300/15 text-left">
          <thead className="bg-ink-300/5 text-xs font-semibold text-ink-500">
            <tr>
              <th className="w-16 px-3 py-2">Order</th>
              <th className="w-28 px-3 py-2">Export</th>
              <th className="px-3 py-2">Fields</th>
              <th className="px-3 py-2">Display Name</th>
              <th className="w-36 px-3 py-2">Row Handling</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-300/10 bg-white">
            {visibleColumns.map((column) => (
              <tr
                key={column.key}
                className={draggingKey === column.key ? "bg-brand-50" : "hover:bg-brand-50/40"}
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => handleDrop(column.key, event)}
              >
                <td className="px-3 py-3">
                  <button
                    type="button"
                    draggable={!disabled}
                    disabled={disabled}
                    onDragStart={(event) => handleDragStart(column.key, event)}
                    onDragEnd={() => setDraggingKey("")}
                    className="grid size-8 place-items-center rounded-soft text-ink-300 hover:bg-ink-300/10 hover:text-ink-700 disabled:opacity-40"
                    aria-label="Drag to reorder export columns"
                  >
                    ⋮⋮
                  </button>
                </td>
                <td className="px-3 py-3">
                  <label className="inline-flex items-center gap-2 text-sm font-semibold text-ink-700">
                    <input
                      type="checkbox"
                      checked={column.enabled}
                      disabled={disabled}
                      onChange={(event) => changeColumn(column.key, { enabled: event.target.checked })}
                    />
                    {column.enabled ? "Enabled" : "Skipped"}
                  </label>
                </td>
                <td className="px-3 py-3">
                  <div className="min-w-0">
                    <b className="block truncate text-sm text-ink-900">{column.key}</b>
                    <span className="mt-1 inline-flex gap-2 text-xs text-ink-500">
                      {column.source === "array_child" ? <Badge variant="neutral">array detail</Badge> : <Badge variant="neutral">non-array</Badge>}
                    </span>
                  </div>
                </td>
                <td className="px-3 py-3">
                  <input
                    value={column.label}
                    disabled={disabled}
                    onChange={(event) => changeColumn(column.key, { label: event.target.value })}
                    placeholder={exportLabelForKey(column.child_key || column.key)}
                    className="w-full rounded-soft border border-ink-300/15 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/15"
                  />
                </td>
                <td className="px-3 py-3">
                  {column.source === "array_child" ? (
                    <Badge variant="neutral">Detail Field</Badge>
                  ) : (
                    <select
                      value={column.row_mode}
                      disabled={disabled}
                      onChange={(event) => changeColumn(column.key, { row_mode: event.target.value as PromptTagExportColumn["row_mode"] })}
                      className="w-full rounded-soft border border-ink-300/15 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500"
                    >
                      <option value="repeat">Repeat</option>
                      <option value="merge">Merge</option>
                      <option value="split_even">Split Evenly</option>
                    </select>
                  )}
                </td>
              </tr>
            ))}
            {!visibleColumns.length ? (
              <tr><td colSpan={5} className="px-3 py-8 text-center text-sm text-ink-500">No exportable fields</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
