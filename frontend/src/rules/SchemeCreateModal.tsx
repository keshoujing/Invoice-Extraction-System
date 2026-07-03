import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useState } from "react";
import type { Scheme } from "../types";
import { Button } from "../ui/Button";

type Props = {
  open: boolean;
  schemes: Scheme[];
  assignToSupplier: { code: string; name: string } | null;
  saving: boolean;
  onClose: () => void;
  onSubmit: (input: { name: string; inheritFrom: string; assign: boolean }) => Promise<void>;
};

export function SchemeCreateModal({ open, schemes, assignToSupplier, saving, onClose, onSubmit }: Props) {
  const [name, setName] = useState("");
  const [inheritFrom, setInheritFrom] = useState("default");
  const [assign, setAssign] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName("");
    setInheritFrom("default");
    setAssign(true);
    setError(null);
  }, [open]);

  async function handleSubmit() {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Name is required");
      return;
    }
    if (schemes.some((scheme) => scheme.name === trimmed)) {
      setError(`A scheme with this name already exists: ${trimmed}`);
      return;
    }
    try {
      await onSubmit({ name: trimmed, inheritFrom, assign });
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
          <Dialog.Title className="text-lg font-semibold text-ink-900">New Scheme</Dialog.Title>
          <div className="mt-4 space-y-4 text-sm">
            <label className="block">
              <span className="mb-1 block font-medium text-ink-700">Name</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="w-full rounded-soft border border-ink-300/30 px-3 py-2 outline-none focus:border-brand-500"
                autoFocus
              />
            </label>
            <label className="block">
              <span className="mb-1 block font-medium text-ink-700">Inherit From</span>
              <select
                value={inheritFrom}
                onChange={(event) => setInheritFrom(event.target.value)}
                className="w-full rounded-soft border border-ink-300/30 px-3 py-2 outline-none focus:border-brand-500"
              >
                {schemes.map((scheme) => (
                  <option key={scheme.name} value={scheme.name}>{scheme.name}</option>
                ))}
              </select>
              <p className="mt-1 text-xs text-ink-500">Copies the prompt, fields, and export columns on creation.</p>
            </label>
            {assignToSupplier ? (
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={assign}
                  onChange={(event) => setAssign(event.target.checked)}
                  className="accent-brand-600"
                />
                <span className="text-ink-700">Assign to "{assignToSupplier.name || assignToSupplier.code}"</span>
              </label>
            ) : null}
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
