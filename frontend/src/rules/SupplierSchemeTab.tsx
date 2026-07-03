import { useState } from "react";
import type { Supplier } from "../types";
import { useToast } from "../shell/ToastHost";
import { Segmented } from "../ui/Segmented";
import { SpinnerPanel } from "../ui/Spinner";
import { RulesIO } from "./RulesIO";
import { SupplierAutoArchiveModal } from "./SupplierAutoArchiveModal";
import { SchemeCreateModal } from "./SchemeCreateModal";
import { SchemeEditor } from "./SchemeEditor";
import { SchemeLibraryPanel } from "./SchemeLibraryPanel";
import { SupplierCreateModal } from "./SupplierCreateModal";
import { SupplierListPanel } from "./SupplierListPanel";
import { useAutoArchiveActive } from "./useAutoArchiveActive";
import { useSchemes } from "./useSchemes";
import { useSuppliers } from "./useSuppliers";

type ViewMode = "suppliers" | "schemes";

export default function SupplierSchemeTab() {
  const toast = useToast();
  const schemes = useSchemes();
  const suppliers = useSuppliers();
  const autoArchive = useAutoArchiveActive();
  const [mode, setMode] = useState<ViewMode>("suppliers");
  const [createSchemeFor, setCreateSchemeFor] = useState<Supplier | null>(null);
  const [autoArchiveSupplier, setAutoArchiveSupplier] = useState<Supplier | null>(null);
  const [showCreateScheme, setShowCreateScheme] = useState(false);
  const [showCreateSupplier, setShowCreateSupplier] = useState(false);

  if (schemes.loading || suppliers.loading) {
    return <SpinnerPanel label="Loading supplier schemes" />;
  }

  async function handleAssign(code: string, schemeName: string) {
    try {
      await suppliers.assignScheme(code, schemeName);
      await schemes.refresh();
      toast.success(`Assigned to scheme: ${schemeName}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Assignment failed");
    }
  }

  async function handleClear(code: string) {
    try {
      await suppliers.clearScheme(code);
      await schemes.refresh();
      toast.success("Restored to default");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Clear failed");
    }
  }

  async function handleDeleteSupplier(supplier: Supplier) {
    const assignedCount = suppliers.map[supplier.code] ? 1 : 0;
    const confirmed = window.confirm(
      `Delete supplier "${supplier.name}"(${supplier.code})？\n\n`
      + `Impact: removes ${assignedCount} scheme bindings and deletes telemetry and learning data.\n`
      + "Historical invoice records are retained."
    );
    if (!confirmed) return;
    try {
      await suppliers.deleteSupplier(supplier.code);
      await schemes.refresh();
      toast.success("Supplier deleted");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Delete failed");
    }
  }

  async function handleCreateScheme(input: { name: string; inheritFrom: string; assign: boolean }) {
    const created = await schemes.createScheme(input.name, input.inheritFrom);
    if (input.assign && createSchemeFor) {
      await suppliers.assignScheme(createSchemeFor.code, created.name);
      await Promise.all([schemes.refresh(created.name), suppliers.refresh()]);
    }
    toast.success(`Scheme created: ${created.name}`);
  }

  function handleEditSchemeFor(supplier: Supplier) {
    setAutoArchiveSupplier(supplier);
  }

  async function handleDeleteScheme(scheme: { name: string; supplier_count: number }) {
    const message = scheme.supplier_count > 0
      ? `${scheme.supplier_count} suppliers will be restored to default. Continue?`
      : `Delete scheme "${scheme.name}"？`;
    if (!window.confirm(message)) return;
    try {
      await schemes.deleteScheme(scheme.name);
      await suppliers.refresh();
      toast.success("Scheme deleted");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Delete failed");
    }
  }

  const disabled = schemes.saving || suppliers.working;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Segmented
          value={mode}
          onChange={setMode}
          ariaLabel="Rules view"
          options={[
            { value: "suppliers", label: "Supplier" },
            { value: "schemes", label: "Scheme Library" }
          ]}
        />
        <RulesIO
          hasUnsavedChanges={schemes.hasUnsavedChanges}
          disabled={disabled}
          onImported={async () => {
            await Promise.all([schemes.refresh(), suppliers.refresh()]);
          }}
          onSuccess={toast.success}
          onError={toast.error}
        />
      </div>

      {mode === "suppliers" ? (
        <SupplierListPanel
          suppliers={suppliers.suppliers}
          map={suppliers.map}
          schemes={schemes.schemes}
          disabled={disabled}
          autoArchiveActive={autoArchive.active}
          onAssign={(code, schemeName) => void handleAssign(code, schemeName)}
          onClear={(code) => void handleClear(code)}
          onDelete={(supplier) => void handleDeleteSupplier(supplier)}
          onCreateNewSchemeFor={(supplier) => {
            setCreateSchemeFor(supplier);
            setShowCreateScheme(true);
          }}
          onEditSchemeFor={handleEditSchemeFor}
          onAddSupplier={() => setShowCreateSupplier(true)}
        />
      ) : (
        <div className="flex items-start gap-4">
          <SchemeLibraryPanel
            schemes={schemes.schemes}
            selectedName={schemes.selectedName}
            onSelect={schemes.selectName}
            onCreate={() => {
              setCreateSchemeFor(null);
              setShowCreateScheme(true);
            }}
          />
          <SchemeEditor
            scheme={schemes.selectedScheme}
            draft={schemes.selectedDraft}
            saving={schemes.saving}
            hasUnsavedChanges={schemes.hasUnsavedChanges}
            onDraftChange={schemes.updateDraft}
            onSave={async () => {
              try {
                const saved = await schemes.saveScheme();
                if (saved) toast.success(`Scheme saved: ${saved.name}`);
              } catch (error) {
                toast.error(error instanceof Error ? error.message : "Save failed");
              }
            }}
            onDelete={handleDeleteScheme}
          />
        </div>
      )}

      <SchemeCreateModal
        open={showCreateScheme}
        schemes={schemes.schemes}
        assignToSupplier={createSchemeFor}
        saving={schemes.saving}
        onClose={() => {
          setShowCreateScheme(false);
          setCreateSchemeFor(null);
        }}
        onSubmit={handleCreateScheme}
      />

      <SupplierCreateModal
        open={showCreateSupplier}
        saving={suppliers.working}
        onClose={() => setShowCreateSupplier(false)}
        onSubmit={async ({ code, name }) => {
          await suppliers.createSupplier(code, name);
          toast.success(`Supplier created: ${name}`);
        }}
      />

      <SupplierAutoArchiveModal
        open={Boolean(autoArchiveSupplier)}
        supplier={autoArchiveSupplier}
        onClose={() => setAutoArchiveSupplier(null)}
        onSuccess={(msg) => { toast.success(msg); autoArchive.refresh(); }}
        onError={toast.error}
      />
    </div>
  );
}
