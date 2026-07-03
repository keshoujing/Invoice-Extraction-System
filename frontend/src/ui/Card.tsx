import type { ComponentPropsWithoutRef, ReactNode } from "react";

type CardProps = ComponentPropsWithoutRef<"section"> & {
  hover?: boolean;
  children: ReactNode;
};

export function Card({ hover = false, className = "", children, ...props }: CardProps) {
  const classes = [
    "rounded-card bg-card shadow-card",
    "border border-ink-300/10",
    "transition-shadow duration-fast ease-std",
    hover ? "hover:shadow-cardH" : "",
    className
  ].filter(Boolean).join(" ");

  return (
    <section className={classes} {...props}>
      {children}
    </section>
  );
}

type CardHeaderProps = ComponentPropsWithoutRef<"div"> & {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
};

export function CardHeader({ title, description, actions, className = "", ...props }: CardHeaderProps) {
  return (
    <div className={["flex items-start justify-between gap-4 border-b border-ink-300/10 p-5", className].filter(Boolean).join(" ")} {...props}>
      <div className="min-w-0">
        <h2 className="truncate text-base font-semibold text-ink-900">{title}</h2>
        {description ? <p className="mt-1 text-sm text-ink-500">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

type CardBodyProps = ComponentPropsWithoutRef<"div"> & {
  children: ReactNode;
};

export function CardBody({ children, className = "", ...props }: CardBodyProps) {
  return (
    <div className={["p-5", className].filter(Boolean).join(" ")} {...props}>
      {children}
    </div>
  );
}
