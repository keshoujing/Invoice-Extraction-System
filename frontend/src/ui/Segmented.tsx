import { motion } from "motion/react";
import type { ReactNode } from "react";

export type SegmentedOption<T extends string> = {
  value: T;
  label: ReactNode;
  disabled?: boolean;
};

type SegmentedProps<T extends string> = {
  value: T;
  options: SegmentedOption<T>[];
  onChange: (value: T) => void;
  ariaLabel: string;
  className?: string;
};

export function Segmented<T extends string>({ value, options, onChange, ariaLabel, className = "" }: SegmentedProps<T>) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={["inline-flex rounded-pill bg-ink-300/10 p-1", className].filter(Boolean).join(" ")}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={option.disabled}
            onClick={() => onChange(option.value)}
            className={[
              "relative min-w-20 rounded-pill px-3 py-1.5 text-sm font-semibold outline-none transition-colors duration-fast ease-sharp",
              selected ? "text-brand-700" : "text-ink-500 hover:text-ink-900",
              "disabled:pointer-events-none disabled:opacity-45"
            ].join(" ")}
          >
            {selected ? (
              <motion.span
                layoutId="segmented-active-chip"
                className="absolute inset-0 rounded-pill bg-card shadow-card"
                transition={{ duration: 0.18, ease: [0.4, 0, 0.6, 1] }}
              />
            ) : null}
            <span className="relative z-10">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
