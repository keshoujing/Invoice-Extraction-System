import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useState } from "react";
import { Button } from "../ui/Button";

type Props = {
  open: boolean;
  saving: boolean;
  onClose: () => void;
  onSubmit: (input: { code: string; name: string }) => Promise<void>;
};

export function SupplierCreateModal({ open, saving, onClose, onSubmit }: Props) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setCode("");
    setName("");
    setError(null);
  }, [open]);

  async function handleSubmit() {
    const cleanCode = code.trim();
    const cleanName = name.trim();
    if (!cleanCode || !cleanName) {
      setError("Code and name cannot both be blank");
      return;
    }
    try {
      await onSubmit({ code: cleanCode, name: cleanName });
      onClose();
    } catch (errorValue) {
      setError(errorValue instanceof Error ? errorValue.message : "Create failed");
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={(nextOpen) => !nextOpen && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(92vw,420px)] -translate-x-1/2 -translate-y-1/2 rounded-card bg-white p-6 shadow-cardH">
          <Dialog.Title className="text-lg font-semibold text-ink-900">Add Supplier</Dialog.Title>
          <div className="mt-4 space-y-4 text-sm">
            <label className="block">
              <span className="mb-1 block font-medium text-ink-700">Code</span>
              <input
                value={code}
                onChange={(event) => setCode(event.target.value)}
                className="w-full rounded-soft border border-ink-300/30 px-3 py-2 outline-none focus:border-brand-500"
                autoFocus
              />
            </label>
            <label className="block">
              <span className="mb-1 block font-medium text-ink-700">Name</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="w-full rounded-soft border border-ink-300/30 px-3 py-2 outline-none focus:border-brand-500"
              />
            </label>
            <p className="rounded-soft border border-amber-300/40 bg-amber-50 p-2 text-xs text-amber-700">
              Note: code and name cannot be changed after creation. Delete and recreate the supplier to correct them.
            </p>
            {error ? <p className="text-sm text-danger-text">{error}</p> : null}
          </div>
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose} disabled={saving}>Cancel</Button>
            <Button variant="primary" onClick={() => void handleSubmit()} disabled={saving}>{saving ? "Creating" : "Create"}</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
