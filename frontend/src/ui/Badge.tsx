import type { ComponentPropsWithoutRef, ReactNode } from "react";

export type BadgeVariant = "ok" | "warn" | "danger" | "neutral";

type BadgeProps = ComponentPropsWithoutRef<"span"> & {
  variant?: BadgeVariant;
  children: ReactNode;
};

const badgeClasses: Record<BadgeVariant, string> = {
  ok: "bg-ok-bg text-ok-text",
  warn: "bg-warn-bg text-warn-text",
  danger: "bg-danger-bg text-danger-text",
  neutral: "bg-ink-300/10 text-ink-500"
};

export function Badge({ variant = "neutral", className = "", children, ...props }: BadgeProps) {
  return (
    <span
      className={[
        "inline-flex items-center rounded-pill px-2 py-0.5 text-xs font-semibold leading-5",
        badgeClasses[variant],
        className
      ].filter(Boolean).join(" ")}
      {...props}
    >
      {children}
    </span>
  );
}

export function StatusDot({ variant = "neutral", className = "" }: Pick<BadgeProps, "variant" | "className">) {
  const dotClasses: Record<BadgeVariant, string> = {
    ok: "bg-ok-text",
    warn: "bg-warn-text",
    danger: "bg-danger-text",
    neutral: "bg-ink-300"
  };

  return (
    <span
      aria-hidden="true"
      className={["inline-block size-2 rounded-pill", dotClasses[variant], className].filter(Boolean).join(" ")}
    />
  );
}
