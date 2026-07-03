import * as Dialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";

type ModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
};

export function Modal({ open, onOpenChange, title, description, children, footer }: ModalProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink-900/30 backdrop-blur-[1px] data-[state=closed]:animate-out data-[state=closed]:fade-out data-[state=open]:animate-in data-[state=open]:fade-in" />
        <Dialog.Content
          className={[
            "fixed left-1/2 top-1/2 z-50 flex max-h-[min(620px,calc(100dvh-2rem))] w-[calc(100vw-2rem)] max-w-[420px] -translate-x-1/2 -translate-y-1/2 flex-col rounded-card border border-ink-300/15 bg-card shadow-cardH outline-none",
            "data-[state=closed]:animate-out data-[state=closed]:fade-out data-[state=closed]:zoom-out-95",
            "data-[state=open]:animate-in data-[state=open]:fade-in data-[state=open]:zoom-in-95",
            "duration-fast ease-out"
          ].join(" ")}
        >
          <div className="flex items-start justify-between gap-4 border-b border-ink-300/15 p-5">
            <div className="min-w-0">
              <Dialog.Title className="text-base font-semibold text-ink-900">{title}</Dialog.Title>
              {description ? <Dialog.Description className="mt-1 text-sm text-ink-500">{description}</Dialog.Description> : null}
            </div>
            <Dialog.Close className="rounded-soft px-2 py-1 text-xl leading-none text-ink-500 transition-colors duration-micro hover:bg-brand-50 hover:text-brand-700">
              ×
            </Dialog.Close>
          </div>
          <div className="min-h-0 overflow-y-auto p-5">{children}</div>
          {footer ? <div className="border-t border-ink-300/15 p-5">{footer}</div> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
