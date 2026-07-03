import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

type FieldProps = {
  label: ReactNode;
  htmlFor?: string;
  error?: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
};

const controlClasses = [
  "w-full rounded-soft border bg-white px-3 py-2 text-sm text-ink-900 outline-none",
  "transition-[border-color,box-shadow] duration-micro ease-std placeholder:text-ink-300",
  "focus:border-brand-500 focus:ring-2 focus:ring-brand-500/15"
].join(" ");

export function Field({ label, htmlFor, error, hint, children, className = "" }: FieldProps) {
  return (
    <label className={["block space-y-1.5", className].filter(Boolean).join(" ")} htmlFor={htmlFor}>
      <span className="flex items-center justify-between gap-3 text-xs font-semibold uppercase tracking-[0.04em] text-ink-500">
        {label}
        {hint ? <span className="normal-case tracking-normal text-ink-300">{hint}</span> : null}
      </span>
      {children}
      {error ? <span className="block text-xs font-semibold text-danger-text">{error}</span> : null}
    </label>
  );
}

export function TextInput({ className = "", "aria-invalid": ariaInvalid, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={[
        controlClasses,
        ariaInvalid ? "border-danger-text/50 ring-2 ring-danger-text/10" : "border-ink-300/25",
        className
      ].filter(Boolean).join(" ")}
      aria-invalid={ariaInvalid}
      {...props}
    />
  );
}

export function TextArea({ className = "", "aria-invalid": ariaInvalid, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={[
        controlClasses,
        "min-h-24 resize-y",
        ariaInvalid ? "border-danger-text/50 ring-2 ring-danger-text/10" : "border-ink-300/25",
        className
      ].filter(Boolean).join(" ")}
      aria-invalid={ariaInvalid}
      {...props}
    />
  );
}

export function SelectInput({ className = "", "aria-invalid": ariaInvalid, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={[
        controlClasses,
        ariaInvalid ? "border-danger-text/50 ring-2 ring-danger-text/10" : "border-ink-300/25",
        className
      ].filter(Boolean).join(" ")}
      aria-invalid={ariaInvalid}
      {...props}
    />
  );
}
