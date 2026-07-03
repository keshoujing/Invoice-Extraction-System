import { useEffect, useMemo, useState } from "react";
import { exportArchive, selectDirectory } from "../api";
import type { Invoice } from "../types";
import { Button } from "../ui/Button";
import { Drawer } from "../ui/Drawer";
import { Field, TextInput } from "../ui/Field";
import { useToast } from "../shell/ToastHost";
import { STORAGE_KEYS } from "../lib/constants";
import { advanceStartNumber, formatAmount } from "../lib/format";
import { extensionForInvoice } from "../lib/invoice";
import { storedBool, storedString, storeBool, storeString } from "../lib/storage";
import type { ExportArchiveFilters } from "./useConfirmedFilters";

type ExportDrawerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  invoices: Invoice[];
  exportFilters: ExportArchiveFilters;
  onExported: () => Promise<void>;
  onClearSelection: () => void;
};

const RECENT_FOLDERS_KEY = "invoiceArchive.export.recentFolders";

function storedRecentFolders(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const value = JSON.parse(window.localStorage.getItem(RECENT_FOLDERS_KEY) || "[]");
    return Array.isArray(value)
      ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0).slice(0, 5)
      : [];
  } catch {
    return [];
  }
}

function storeRecentFolder(path: string): void {
  if (typeof window === "undefined" || !path.trim()) return;
  const next = [path, ...storedRecentFolders().filter((item) => item !== path)].slice(0, 5);
  window.localStorage.setItem(RECENT_FOLDERS_KEY, JSON.stringify(next));
}

function archiveNumber(prefix: string, startNumber: string, index: number): string {
  const start = Number.parseInt(startNumber || "0", 10);
  const width = Math.max(4, startNumber.length);
  if (!Number.isFinite(start)) return `${prefix}${startNumber}`;
  return `${prefix}${String(start + index).padStart(width, "0")}`;
}

export function ExportDrawer({
  open,
  onOpenChange,
  invoices,
  exportFilters,
  onExported,
  onClearSelection
}: ExportDrawerProps) {
  const toast = useToast();
  const [destinationDir, setDestinationDir] = useState(() => storedString(STORAGE_KEYS.exportDestinationDir, ""));
  const [prefix, setPrefix] = useState(() => storedString(STORAGE_KEYS.exportPrefix, "A26"));
  const [startNumber, setStartNumber] = useState(() => storedString(STORAGE_KEYS.exportStartNumber, "0001"));
  const [createNewFolder, setCreateNewFolder] = useState(() => storedBool(STORAGE_KEYS.exportCreateNewFolder, false));
  const [recentFolders, setRecentFolders] = useState<string[]>(storedRecentFolders);
  const [busy, setBusy] = useState(false);
  const [selecting, setSelecting] = useState(false);

  useEffect(() => storeString(STORAGE_KEYS.exportDestinationDir, destinationDir), [destinationDir]);
  useEffect(() => storeString(STORAGE_KEYS.exportPrefix, prefix), [prefix]);
  useEffect(() => storeString(STORAGE_KEYS.exportStartNumber, startNumber), [startNumber]);
  useEffect(() => storeBool(STORAGE_KEYS.exportCreateNewFolder, createNewFolder), [createNewFolder]);

  const previewRows = useMemo(() => {
    return invoices.map((invoice, index) => {
      const number = archiveNumber(prefix, startNumber, index);
      return {
        invoice,
        archiveNumber: number,
        filename: `${number}${extensionForInvoice(invoice)}`
      };
    });
  }, [invoices, prefix, startNumber]);

  const totalAmount = useMemo(
    () => invoices.reduce((sum, invoice) => sum + Number(invoice.total_amount || 0), 0),
    [invoices]
  );

  const canExport = Boolean(destinationDir && prefix && startNumber && invoices.length && !busy);

  const chooseFolder = async () => {
    setSelecting(true);
    try {
      const selected = await selectDirectory();
      if (selected.path) {
        setDestinationDir(selected.path);
        storeRecentFolder(selected.path);
        setRecentFolders(storedRecentFolders());
        toast.success("Export destination selected");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to choose folder");
    } finally {
      setSelecting(false);
    }
  };

  const confirmExport = async () => {
    if (!canExport) return;
    setBusy(true);
    try {
      const result = await exportArchive({
        destination_dir: destinationDir,
        prefix,
        start_number: startNumber,
        invoice_ids: invoices.map((invoice) => invoice.id),
        create_new_folder: createNewFolder,
        filters: exportFilters
      });
      setStartNumber(advanceStartNumber(startNumber, result.item_count));
      storeRecentFolder(destinationDir);
      setRecentFolders(storedRecentFolders());
      onClearSelection();
      await onExported();
      toast.success(`Export complete: ${result.item_count} files`);
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Export failed");
    } finally {
      setBusy(false);
    }
  };

  const footer = (
    <div className="flex justify-end gap-2">
      <Button onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
      <Button variant="primary" onClick={confirmExport} disabled={!canExport}>
        {busy ? "Exporting..." : "Confirm Export"}
      </Button>
    </div>
  );

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="Export Confirmed Invoices"
      description={`${invoices.length} invoices · Amount ${formatAmount(totalAmount)}`}
      footer={footer}
      width={480}
    >
      <div className="grid gap-5">
        <div className="rounded-card bg-brand-50 px-4 py-3 text-sm font-semibold text-brand-700">
          Selected {invoices.length} invoices
        </div>

        <Field label="Destination Folder">
          <div className="flex gap-2">
            <TextInput value={destinationDir} readOnly placeholder="Choose an export folder" onClick={chooseFolder} />
            <Button onClick={chooseFolder} disabled={busy || selecting} className="shrink-0">
              {selecting ? "Choosing" : "Choose"}
            </Button>
          </div>
        </Field>

        {recentFolders.length ? (
          <div className="space-y-2">
            <div className="text-xs font-semibold uppercase tracking-[0.04em] text-ink-500">Existing Folders</div>
            <div className="grid gap-2">
              {recentFolders.map((folder) => (
                <button
                  key={folder}
                  type="button"
                  onClick={() => setDestinationDir(folder)}
                  className="truncate rounded-soft bg-ink-300/10 px-3 py-2 text-left text-sm text-ink-700 transition-colors duration-micro hover:bg-brand-50 hover:text-brand-700"
                >
                  {folder}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        <label className="flex items-center justify-between gap-3 rounded-soft border border-ink-300/15 bg-white px-3 py-2 text-sm font-semibold text-ink-700">
          <span>Create New Folder</span>
          <input type="checkbox" checked={createNewFolder} onChange={(event) => setCreateNewFolder(event.target.checked)} />
        </label>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Filename Prefix">
            <TextInput value={prefix} onChange={(event) => setPrefix(event.target.value.toUpperCase())} />
          </Field>
          <Field label="Start Number">
            <TextInput value={startNumber} onChange={(event) => setStartNumber(event.target.value.replace(/\D/g, ""))} inputMode="numeric" />
          </Field>
        </div>

        <div className="min-h-0 rounded-card border border-ink-300/15">
          <div className="border-b border-ink-300/15 px-3 py-2 text-xs font-semibold uppercase tracking-[0.04em] text-ink-500">
            File Preview
          </div>
          <div className="max-h-72 divide-y divide-ink-300/15 overflow-auto">
            {previewRows.map((row) => (
              <div key={row.invoice.id} className="grid gap-1 px-3 py-2 text-sm">
                <span className="truncate font-semibold text-ink-900">{row.filename}</span>
                <span className="truncate text-xs text-ink-500">{row.invoice.vendor_name || "Unnamed Supplier"} · {row.invoice.invoice_number || "No invoice number"}</span>
              </div>
            ))}
            {!previewRows.length ? <div className="px-3 py-8 text-center text-sm text-ink-300">No selected invoices</div> : null}
          </div>
        </div>
      </div>
    </Drawer>
  );
}
