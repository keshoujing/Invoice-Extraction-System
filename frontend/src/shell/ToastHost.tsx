import { AnimatePresence, motion } from "motion/react";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

export type ToastTone = "success" | "error" | "info";

export type ToastMessage = {
  id: string;
  message: string;
  tone: ToastTone;
  updatedAt: number;
};

type ToastContextValue = {
  toasts: ToastMessage[];
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
  upsert: (id: string, tone: ToastTone, message: string) => void;
  dismiss: (id: string) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

const toneClasses: Record<ToastTone, string> = {
  success: "border-ok-text/15 bg-ok-bg text-ok-text",
  error: "border-danger-text/15 bg-danger-bg text-danger-text",
  info: "border-brand-500/15 bg-brand-50 text-brand-700"
};

type ToastProviderProps = {
  children: ReactNode;
};

export function ToastProvider({ children }: ToastProviderProps) {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback((tone: ToastTone, message: string) => {
    const id = `${Date.now()}-${Math.round(Math.random() * 1000)}`;
    setToasts((current) => [...current, { id, tone, message, updatedAt: Date.now() }].slice(-4));
  }, []);

  const upsert = useCallback((id: string, tone: ToastTone, message: string) => {
    setToasts((current) => {
      const existing = current.find((toast) => toast.id === id);
      if (!existing) return [...current, { id, tone, message, updatedAt: Date.now() }].slice(-4);
      return current.map((toast) => (
        toast.id === id ? { ...toast, tone, message, updatedAt: Date.now() } : toast
      ));
    });
  }, []);

  const success = useCallback((message: string) => push("success", message), [push]);
  const error = useCallback((message: string) => push("error", message), [push]);
  const info = useCallback((message: string) => push("info", message), [push]);

  const value = useMemo<ToastContextValue>(() => ({
    toasts,
    success,
    error,
    info,
    upsert,
    dismiss
  }), [dismiss, error, info, success, toasts, upsert]);

  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>;
}

export function useToast(): Omit<ToastContextValue, "toasts"> {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used inside ToastProvider");
  }
  return useMemo(() => ({
    success: context.success,
    error: context.error,
    info: context.info,
    upsert: context.upsert,
    dismiss: context.dismiss
  }), [context.dismiss, context.error, context.info, context.success, context.upsert]);
}

function ToastItem({ toast }: { toast: ToastMessage }) {
  const { dismiss } = useToast();

  useEffect(() => {
    const handle = window.setTimeout(() => {
      dismiss(toast.id);
    }, 3200);
    return () => window.clearTimeout(handle);
  }, [dismiss, toast.id, toast.updatedAt]);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.24, ease: [0, 0, 0.2, 1] }}
      className={[
        "pointer-events-auto flex min-w-72 max-w-[min(92vw,520px)] items-center justify-between gap-4 rounded-card border px-4 py-3 shadow-cardH",
        toneClasses[toast.tone]
      ].join(" ")}
    >
      <span className="text-sm font-semibold">{toast.message}</span>
      <button type="button" onClick={() => dismiss(toast.id)} className="rounded-soft px-2 py-1 text-sm opacity-70 hover:bg-white/45 hover:opacity-100">
        ×
      </button>
    </motion.div>
  );
}

export function ToastHost() {
  const context = useContext(ToastContext);
  if (!context) return null;

  return (
    <div className="pointer-events-none fixed inset-x-0 top-4 z-[60] flex flex-col items-center gap-2 px-4">
      <AnimatePresence initial={false}>
        {context.toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} />
        ))}
      </AnimatePresence>
    </div>
  );
}
