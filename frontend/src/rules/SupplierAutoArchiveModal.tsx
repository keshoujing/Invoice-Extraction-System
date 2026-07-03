import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useEffect, useMemo, useState } from "react";
import { getSupplierAutoArchiveConfig, updateSupplierAutoArchiveConfig } from "../api";
import type { Supplier, SupplierAutoArchiveCheck, SupplierAutoArchiveConfig } from "../types";
import { Badge } from "../ui/Badge";
import { Button, IconButton } from "../ui/Button";
import { Modal } from "../ui/Modal";

type Props = {
  supplier: Supplier | null;
  open: boolean;
  onClose: () => void;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
};

function Toggle({
  checked,
  onChange,
  disabled
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={[
        "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full",
        "transition-colors duration-fast focus-visible:outline-none focus-visible:ring-2",
        "focus-visible:ring-brand-500 focus-visible:ring-offset-2",
        "disabled:pointer-events-none disabled:opacity-50",
        checked ? "bg-brand-500" : "bg-ink-300/30"
      ].join(" ")}
    >
      <span
        className={[
          "pointer-events-none block h-4 w-4 translate-y-0.5 rounded-full bg-white shadow-sm",
          "transition-transform duration-fast",
          checked ? "translate-x-[18px]" : "translate-x-0.5"
        ].join(" ")}
      />
    </button>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" className="size-4" aria-hidden="true">
      <path d="M5.5 5.5A.5.5 0 0 1 6 6v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5m2.5 0a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5m3 .5a.5.5 0 0 0-1 0v6a.5.5 0 0 0 1 0z" />
      <path d="M14.5 3a1 1 0 0 1-1 1H13v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4h-.5a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1H6a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1h3.5a1 1 0 0 1 1 1zM4.118 4 4 4.059V13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V4.059L11.882 4zM2.5 3h11V2h-11z" />
    </svg>
  );
}

export function SupplierAutoArchiveModal({ supplier, open, onClose, onSuccess, onError }: Props) {
  const [config, setConfig] = useState<SupplierAutoArchiveConfig | null>(null);
  const [checks, setChecks] = useState<SupplierAutoArchiveCheck[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || !supplier) return;
    setLoading(true);
    getSupplierAutoArchiveConfig(supplier.code)
      .then((next) => {
        setConfig(next);
        setChecks(next.checks);
      })
      .catch((error) => onError(error instanceof Error ? error.message : "Failed to load auto-archive configuration"))
      .finally(() => setLoading(false));
  }, [onError, open, supplier]);

  const availableToAdd = useMemo(() => {
    const used = new Set(checks.map((check) => check.field_key.toLowerCase()));
    return (config?.available_fields || []).filter((field) => !used.has(field.toLowerCase()));
  }, [checks, config]);

  function updateCheck(index: number, patch: Partial<SupplierAutoArchiveCheck>) {
    setChecks((current) => current.map((item, itemIndex) => (
      itemIndex === index ? { ...item, ...patch } : item
    )));
  }

  function addField(fieldKey: string) {
    if (!fieldKey) return;
    setChecks((current) => [
      ...current,
      { field_key: fieldKey, enabled: true, baseline_value: "", tolerance_percent: "" }
    ]);
  }

  function removeCheck(index: number) {
    setChecks((current) => current.filter((_, i) => i !== index));
  }

  async function save() {
    if (!supplier || !config) return;
    const invalid = checks.find((check) => check.enabled && (!check.baseline_value.trim() || !check.tolerance_percent.trim()));
    if (invalid) {
      onError(`Please enter ${invalid.field_key} baseline and tolerance`);
      return;
    }
    const confirmed = window.confirm("Saving affects future auto-archive decisions for this supplier. Confirm the baseline comes from a stable invoice amount.");
    if (!confirmed) return;
    setSaving(true);
    try {
      const next = await updateSupplierAutoArchiveConfig(supplier.code, checks);
      setConfig(next);
      setChecks(next.checks);
      onSuccess("Auto-archive checks saved");
      onClose();
    } catch (error) {
      onError(error instanceof Error ? error.message : "Failed to save auto-archive configuration");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={(next) => { if (!next && !saving) onClose(); }}
      title={
        supplier ? (
          <div>
            <p className="mb-0.5 text-xs font-semibold uppercase tracking-widest text-ink-400">{supplier.name}</p>
            <span>Auto-Archive Checks</span>
          </div>
        ) : "Auto-Archive Checks"
      }
      footer={
        <div className="flex justify-end gap-2">
          <Button disabled={saving} onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={saving || loading || !config} onClick={() => void save()}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      }
    >
      {loading ? (
        <div className="py-8 text-center text-sm font-semibold text-ink-500">Loading...</div>
      ) : !config ? (
        <div className="py-8 text-center text-sm font-semibold text-ink-500">No configuration</div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-1.5 rounded-soft bg-brand-50 px-3 py-2 text-xs text-ink-600">
            <span className="shrink-0 text-brand-400" aria-hidden="true">ⓘ</span>
            <span>
              Current scheme{" "}
              <Badge variant="ok" className="mx-0.5">{config.scheme_name}</Badge>
              {" "}· Only value fields from this scheme can be added
            </span>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-semibold text-ink-900">Check Fields</span>
              <span className="text-xs text-ink-400">{checks.length} fields</span>
            </div>

            {checks.length > 0 && (
              <div className="mb-2 space-y-2">
                {checks.map((check, index) => (
                  <div key={check.field_key} className="rounded-card border border-ink-300/10 bg-white p-3">
                    <div className="flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate rounded-soft bg-brand-100 px-2.5 py-1 font-mono text-sm font-semibold text-brand-700">
                        {check.field_key}
                      </span>
                      <div className="flex shrink-0 items-center gap-1.5">
                        <span className="text-xs font-medium text-ink-500">Enabled</span>
                        <Toggle
                          checked={check.enabled}
                          onChange={(v) => updateCheck(index, { enabled: v })}
                          disabled={saving}
                        />
                      </div>
                      <IconButton
                        onClick={() => removeCheck(index)}
                        disabled={saving}
                        aria-label="Delete this check field"
                        title="Delete"
                        className="text-ink-400 hover:text-danger-text hover:bg-danger-bg"
                      >
                        <TrashIcon />
                      </IconButton>
                    </div>
                    <div className="mt-2 flex gap-2">
                      <div className="flex-1">
                        <label className="mb-1 block text-xs text-ink-500">Baseline</label>
                        <input
                          value={check.baseline_value}
                          inputMode="decimal"
                          onChange={(event) => updateCheck(index, { baseline_value: event.target.value })}
                          placeholder="Enter baseline"
                          disabled={saving}
                          className="w-full rounded-soft border border-ink-300/15 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/15 disabled:bg-ink-300/5"
                        />
                      </div>
                      <div className="w-28">
                        <label className="mb-1 block text-xs text-ink-500">Tolerance (%)</label>
                        <div className="relative">
                          <input
                            value={check.tolerance_percent}
                            inputMode="decimal"
                            onChange={(event) => updateCheck(index, { tolerance_percent: event.target.value })}
                            disabled={saving}
                            className="w-full rounded-soft border border-ink-300/15 bg-white px-3 py-2 pr-7 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/15 disabled:bg-ink-300/5"
                          />
                          <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-ink-400">%</span>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {availableToAdd.length > 0 ? (
              <DropdownMenu.Root>
                <DropdownMenu.Trigger asChild>
                  <button
                    type="button"
                    disabled={saving}
                    className="flex w-full items-center justify-between rounded-card border border-dashed border-ink-300/30 px-3 py-2.5 text-sm text-ink-500 transition-colors hover:border-brand-300 hover:bg-brand-50/70 hover:text-brand-700 disabled:pointer-events-none disabled:opacity-50"
                  >
                    <span>+ Add Check Field</span>
                    <span className="text-xs text-ink-400">▾</span>
                  </button>
                </DropdownMenu.Trigger>
                <DropdownMenu.Portal>
                  <DropdownMenu.Content
                    align="start"
                    sideOffset={4}
                    className="z-50 min-w-[220px] rounded-card border border-ink-300/15 bg-white p-1 text-sm shadow-cardH"
                  >
                    {availableToAdd.map((field) => (
                      <DropdownMenu.Item
                        key={field}
                        onSelect={() => addField(field)}
                        className="cursor-pointer rounded-soft px-3 py-2 font-mono outline-none data-[highlighted]:bg-brand-50 data-[highlighted]:text-brand-700"
                      >
                        {field}
                      </DropdownMenu.Item>
                    ))}
                  </DropdownMenu.Content>
                </DropdownMenu.Portal>
              </DropdownMenu.Root>
            ) : (
              <p className="py-1 text-center text-xs text-ink-400">
                {checks.length === 0 ? "No value fields are available in this scheme" : "All value fields have been added"}
              </p>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
