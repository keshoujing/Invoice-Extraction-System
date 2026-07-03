type SpinnerProps = {
  label?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
};

const sizeClasses: Record<NonNullable<SpinnerProps["size"]>, string> = {
  sm: "size-4",
  md: "size-6",
  lg: "size-9"
};

export function Spinner({ label = "Loading", size = "md", className = "" }: SpinnerProps) {
  return (
    <span className={["inline-flex items-center gap-2 text-sm font-medium text-brand-700", className].filter(Boolean).join(" ")} role="status">
      <svg className={[sizeClasses[size], "animate-spin"].join(" ")} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle className="stroke-brand-500/20" cx="12" cy="12" r="9" strokeWidth="3" />
        <circle
          className="stroke-brand-600"
          cx="12"
          cy="12"
          r="9"
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray="42 24"
        />
      </svg>
      <span className="sr-only">{label}</span>
    </span>
  );
}

export function SpinnerPanel({ label = "Loading" }: Pick<SpinnerProps, "label">) {
  return (
    <div className="grid min-h-72 place-items-center">
      <Spinner label={label} size="lg" />
    </div>
  );
}
