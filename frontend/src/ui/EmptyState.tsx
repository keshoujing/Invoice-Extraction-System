import type { ReactNode } from "react";

type EmptyStateProps = {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
};

export function EmptyState({ icon, title, description, action, className = "" }: EmptyStateProps) {
  return (
    <div className={["flex min-h-72 flex-col items-center justify-center px-6 py-12 text-center", className].filter(Boolean).join(" ")}>
      {icon ? (
        <div className="mb-4 grid size-12 place-items-center rounded-card bg-brand-50 text-brand-700">
          {icon}
        </div>
      ) : null}
      <h2 className="text-base font-semibold text-ink-900">{title}</h2>
      {description ? <p className="mt-2 max-w-md text-sm leading-6 text-ink-500">{description}</p> : null}
      {action ? <div className="mt-5 flex items-center justify-center gap-2">{action}</div> : null}
    </div>
  );
}

export function EmptyIcon() {
  return (
    <svg className="size-5" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M5 7.5A2.5 2.5 0 0 1 7.5 5h9A2.5 2.5 0 0 1 19 7.5v9a2.5 2.5 0 0 1-2.5 2.5h-9A2.5 2.5 0 0 1 5 16.5v-9Z"
        stroke="currentColor"
        strokeWidth="1.8"
      />
      <path d="M8 10h8M8 14h5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
