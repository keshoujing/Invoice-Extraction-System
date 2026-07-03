import { AnimatePresence, motion } from "motion/react";
import type { ExportStats } from "../types";

type ExportStatsBarProps = {
  stats: ExportStats;
};

function TickNumber({ value }: { value: number }) {
  return (
    <span className="relative inline-flex min-w-5 justify-end tabular-nums">
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={value}
          initial={{ opacity: 0, y: -6, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 6, scale: 0.98 }}
          transition={{ duration: 0.18, ease: [0, 0, 0.2, 1] }}
        >
          {value}
        </motion.span>
      </AnimatePresence>
    </span>
  );
}

export function ExportStatsBar({ stats }: ExportStatsBarProps) {
  return (
    <p className="flex flex-wrap items-center gap-1.5 text-sm font-semibold text-ink-500">
      <span>Confirmed</span>
      <TickNumber value={stats.confirmed_count} />
      <span className="text-ink-300">·</span>
      <span>Exported</span>
      <TickNumber value={stats.exported_count} />
      <span className="text-ink-300">·</span>
      <span>Unexported</span>
      <TickNumber value={stats.unexported_count} />
    </p>
  );
}
