import { useState } from "react";
import type { SupplierAutoArchiveCheck } from "../types";
import { Button } from "../ui/Button";
import type { AutoArchiveCheckView } from "./autoArchiveChecks";

type Props = {
  checks: AutoArchiveCheckView[];
  disabled?: boolean;
  onSave: (check: SupplierAutoArchiveCheck) => void;
};

export function AutoArchiveCheckPanel({ checks, disabled = false, onSave }: Props) {
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [baseline, setBaseline] = useState("");
  const [tolerance, setTolerance] = useState("");

  if (!checks.length) return null;

  function startEdit(check: AutoArchiveCheckView) {
    setEditingKey(check.key);
    setBaseline(check.baseline_value);
    setTolerance(check.tolerance_percent);
  }

  function save(check: AutoArchiveCheckView) {
    const confirmed = window.confirm("Changing auto-archive checks affects future auto-archive decisions for this supplier. Confirm the baseline comes from a stable invoice amount.");
    if (!confirmed) return;
    onSave({
      field_key: check.key,
      enabled: true,
      baseline_value: baseline.trim(),
      tolerance_percent: tolerance.trim()
    });
    setEditingKey(null);
  }

  return (
    <div className="border-t border-ink-300/10 bg-ink-300/[0.025] px-3 py-2">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-[11px] font-bold text-ink-600">Auto-Archive Checks</span>
        <span className="text-[11px] font-semibold text-ink-400">{checks.length} items</span>
      </div>
      <div className="space-y-1">
        {checks.map((check) => {
          const editing = editingKey === check.key;
          return (
            <div key={check.key} className="rounded-soft bg-white/70 px-2 py-1.5">
              <div className="flex min-w-0 items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-[11px] font-semibold text-ink-500">{check.label}</span>
                <span className="shrink-0 text-[11px] font-semibold text-ink-400">
                  {check.baseline_value || "-"} ±{check.tolerance_percent || "-"}%
                </span>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => startEdit(check)}
                  className="shrink-0 rounded-soft px-1.5 py-0.5 text-[11px] font-semibold text-brand-700 hover:bg-brand-50 disabled:opacity-50"
                >
                  Edit
                </button>
              </div>
              {editing ? (
                <div className="mt-2 grid grid-cols-[minmax(0,1fr)_72px_auto_auto] items-center gap-1.5">
                  <input
                    value={baseline}
                    disabled={disabled}
                    inputMode="decimal"
                    onChange={(event) => setBaseline(event.target.value)}
                    className="min-w-0 rounded-soft border border-ink-300/15 bg-white px-2 py-1 text-xs outline-none focus:border-brand-500"
                    placeholder="Baseline"
                  />
                  <input
                    value={tolerance}
                    disabled={disabled}
                    inputMode="decimal"
                    onChange={(event) => setTolerance(event.target.value)}
                    className="min-w-0 rounded-soft border border-ink-300/15 bg-white px-2 py-1 text-xs outline-none focus:border-brand-500"
                    placeholder="%"
                  />
                  <Button className="min-h-7 px-2 py-1 text-xs" disabled={disabled || !baseline.trim() || !tolerance.trim()} onClick={() => save(check)}>Save</Button>
                  <Button className="min-h-7 px-2 py-1 text-xs" variant="ghost" disabled={disabled} onClick={() => setEditingKey(null)}>Cancel</Button>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
