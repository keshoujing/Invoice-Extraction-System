import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "primary" | "ghost" | "danger";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  icon?: ReactNode;
};

const variantClasses: Record<ButtonVariant, string> = {
  primary: "bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-card hover:shadow-cardH",
  ghost: "bg-white text-ink-700 ring-1 ring-ink-300/20 hover:bg-brand-50 hover:text-brand-700",
  danger: "bg-danger-bg text-danger-text ring-1 ring-danger-text/10 hover:ring-danger-text/20"
};

export function Button({
  variant = "ghost",
  icon,
  className = "",
  children,
  type = "button",
  ...props
}: ButtonProps) {
  const classes = [
    "inline-flex min-h-9 items-center justify-center gap-2 rounded-soft px-3.5 py-2",
    "text-sm font-semibold outline-none transition-[transform,box-shadow,background,color] duration-micro ease-std",
    "active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2",
    "disabled:pointer-events-none disabled:opacity-50",
    variantClasses[variant],
    className
  ].filter(Boolean).join(" ");

  return (
    <button type={type} className={classes} {...props}>
      {icon ? <span className="grid size-4 place-items-center">{icon}</span> : null}
      {children}
    </button>
  );
}

export function IconButton({ className = "", children, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type={props.type || "button"}
      className={[
        "grid size-9 place-items-center rounded-soft text-ink-500 outline-none",
        "transition-[transform,background,color] duration-micro ease-std",
        "hover:bg-brand-50 hover:text-brand-700 active:scale-[0.98]",
        "focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2",
        className
      ].filter(Boolean).join(" ")}
      {...props}
    >
      {children}
    </button>
  );
}
