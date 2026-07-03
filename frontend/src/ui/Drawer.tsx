import * as Dialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";

export type DrawerWidth = 420 | 480 | 560 | 640 | 720;

type DrawerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: DrawerWidth;
};

const widthClasses: Record<DrawerWidth, string> = {
  420: "sm:max-w-[420px]",
  480: "sm:max-w-[480px]",
  560: "sm:max-w-[560px]",
  640: "sm:max-w-[640px]",
  720: "sm:max-w-[720px]"
};

export function Drawer({ open, onOpenChange, title, description, children, footer, width = 480 }: DrawerProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink-900/25 backdrop-blur-[1px] data-[state=closed]:animate-out data-[state=closed]:fade-out data-[state=open]:animate-in data-[state=open]:fade-in" />
        <Dialog.Content
          className={[
            "fixed right-0 top-0 z-50 flex h-dvh w-full flex-col bg-card shadow-cardH outline-none",
            "data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right data-[state=open]:animate-in data-[state=open]:slide-in-from-right",
            "duration-slow ease-in",
            widthClasses[width]
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
          <div className="min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
          {footer ? <div className="border-t border-ink-300/15 p-5">{footer}</div> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
