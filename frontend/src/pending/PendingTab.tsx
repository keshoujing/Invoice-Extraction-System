import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import { getPendingRowStatus, type PendingFilter } from "./helpers";
import { PendingTable } from "./PendingTable";
import { UploadDrop } from "./UploadDrop";
import { usePendingData } from "./usePendingData";
import { WarningDrawer } from "./WarningDrawer";
import { useTab } from "../shell/useTab";
import { useToast } from "../shell/ToastHost";
import type { Invoice } from "../types";
import { Button } from "../ui/Button";
import { Card, CardBody, CardHeader } from "../ui/Card";
import { Segmented } from "../ui/Segmented";

const RULE_MODE_STORAGE_KEY = "invoice-archive.rules.mode";
const SPECIAL_RULE_VENDOR_STORAGE_KEY = "invoice-archive.rules.special.vendor_code";

function CountTick({ value, tone = "neutral" }: { value: number; tone?: "neutral" | "brand" | "warn" | "ok" }) {
  const toneClasses = {
    neutral: "bg-ink-300/10 text-ink-500",
    brand: "bg-brand-50 text-brand-700",
    warn: "bg-warn-bg text-warn-text",
    ok: "bg-ok-bg text-ok-text"
  };

  return (
    <span className={["ml-2 inline-grid min-w-6 place-items-center rounded-pill px-1.5 text-xs", toneClasses[tone]].join(" ")}>
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={value}
          initial={{ opacity: 0, y: -4, scale: 0.92 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 4, scale: 0.92 }}
          transition={{ duration: 0.16, ease: [0.4, 0, 0.2, 1] }}
        >
          {value}
        </motion.span>
      </AnimatePresence>
    </span>
  );
}

export default function PendingTab() {
  const toast = useToast();
  const [, setTab] = useTab();
  const [filter, setFilter] = useState<PendingFilter>("all");
  const [warningInvoice, setWarningInvoice] = useState<Invoice | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const pending = usePendingData(toast);

  const counts = useMemo(() => {
    const next = { all: pending.rows.length, ready: 0, "needs-confirm": 0, recognizing: 0 };
    pending.rows.forEach((invoice) => {
      next[getPendingRowStatus(invoice, pending.activeRecognitionIds).filter] += 1;
    });
    return next;
  }, [pending.activeRecognitionIds, pending.rows]);

  const selectedReadyIds = useMemo(
    () => [...pending.selectedIds].filter((id) => pending.readyIds.includes(id)),
    [pending.readyIds, pending.selectedIds]
  );

  const startDisabled = !selectedReadyIds.length || pending.busy || pending.recognitionActive;
  const startReason = pending.recognitionActive
    ? "Recognition job is running"
    : selectedReadyIds.length
      ? ""
      : "Select ready invoices";

  const options = useMemo(() => [
    { value: "all" as const, label: <>All<CountTick value={counts.all} /></> },
    { value: "ready" as const, label: <>Ready<CountTick value={counts.ready} tone="ok" /></> },
    { value: "needs-confirm" as const, label: <>Needs Confirmation<CountTick value={counts["needs-confirm"]} tone="warn" /></> },
    { value: "recognizing" as const, label: <>Recognizing<CountTick value={counts.recognizing} tone="brand" /></> }
  ], [counts]);

  function openWarning(invoice: Invoice) {
    setWarningInvoice(invoice);
    setDrawerOpen(true);
  }

  function openSpecialPrompt(invoice: Invoice) {
    const code = String(invoice.vendor_code || invoice.extracted_data?.vendor_code || invoice.extracted_data?.supplier_code || "").trim();
    window.sessionStorage.setItem(RULE_MODE_STORAGE_KEY, "special");
    if (code) window.sessionStorage.setItem(SPECIAL_RULE_VENDOR_STORAGE_KEY, code);
    setTab("rules");
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="Pending"
          description="Uploads run supplier preview first. Select ready rows to start full recognition."
          actions={
            <div className="flex flex-col items-end">
              <Button
                variant="primary"
                disabled={startDisabled}
                onClick={() => void pending.startRecognition(selectedReadyIds)}
              >
                Start Recognition ({selectedReadyIds.length})
              </Button>
              {startReason ? <span className="mt-1 text-xs font-medium text-ink-500">{startReason}</span> : null}
            </div>
          }
        />
        <CardBody className="space-y-4">
          <UploadDrop
            disabled={pending.busy || pending.uploadActive}
            isEmpty={!pending.rows.length}
            onFiles={(files) => void pending.uploadFiles(files)}
          />

          {pending.uploadSummary ? (
            <div className="flex flex-wrap items-center gap-2 rounded-soft bg-brand-50 px-3 py-2 text-sm font-medium text-brand-700">
              <span>Upload {pending.uploadSummary.uploaded}</span>
              <span aria-hidden="true">·</span>
              <span>Previewed {pending.uploadSummary.recognized}</span>
              {pending.uploadSummary.scanning ? <span>Supplier Scan Running</span> : <span>Preview Complete</span>}
            </div>
          ) : null}

          <div className="flex flex-wrap items-center justify-between gap-3">
            <Segmented value={filter} options={options} onChange={setFilter} ariaLabel="Pending filter" />
            <div className="flex items-center gap-3 text-sm font-medium text-ink-500">
              <span>Selected {pending.selectedIds.size} · ready {selectedReadyIds.length}</span>
              {pending.selectedIds.size ? (
                <Button
                  variant="danger"
                  className="min-h-8 px-2.5 py-1.5 text-xs"
                  disabled={pending.busy}
                  onClick={() => void pending.deleteSelectedRows()}
                >
                  Delete Selected
                </Button>
              ) : null}
            </div>
          </div>

          <PendingTable
            rows={pending.rows}
            filter={filter}
            selectedIds={pending.selectedIds}
            activeRecognitionIds={pending.activeRecognitionIds}
            isLoading={pending.isLoading}
            deletingId={pending.deletingId}
            previewRetryingId={pending.previewRetryingId}
            mutationVersion={pending.mutationVersion}
            promptTagFor={pending.promptTagFor}
            onToggle={pending.toggleSelection}
            onSelectAll={pending.selectAll}
            onOpenWarning={openWarning}
            onRetryPreview={(id) => void pending.retrySupplierPreviewRow(id)}
            onDelete={(invoice) => void pending.deleteRow(invoice)}
          />
        </CardBody>
      </Card>

      <WarningDrawer
        invoice={warningInvoice}
        open={drawerOpen}
        suppliers={pending.suppliers}
        saving={Boolean(warningInvoice && pending.updatingSupplierId === warningInvoice.id)}
        deleting={Boolean(warningInvoice && pending.deletingId === warningInvoice.id)}
        onOpenChange={setDrawerOpen}
        onSave={pending.updateSupplier}
        onDelete={pending.deleteRow}
        onOpenSpecialPrompt={openSpecialPrompt}
        draftForSupplier={pending.draftForSupplier}
        initialDraftFor={pending.supplierDraftFor}
      />
    </div>
  );
}
