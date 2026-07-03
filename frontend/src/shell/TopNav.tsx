import { motion } from "motion/react";
import type { Tab } from "../lib/constants";
import { tabLabel, tabOrder, useTab } from "./useTab";

function LogoMark() {
  return (
    <div className="grid size-9 place-items-center rounded-card bg-gradient-to-br from-brand-500 to-brand-700 text-sm font-black text-white shadow-card">
      IA
    </div>
  );
}

function TopNavTab({ tab, active, onSelect }: { tab: Tab; active: boolean; onSelect: (tab: Tab) => void }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(tab)}
      className={[
        "relative min-h-10 rounded-soft px-3 text-sm font-semibold outline-none transition-colors duration-fast ease-sharp",
        active ? "text-brand-700" : "text-ink-500 hover:bg-brand-50 hover:text-ink-900",
        "focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2"
      ].join(" ")}
    >
      <span className="relative z-10 whitespace-nowrap">{tabLabel(tab)}</span>
      {active ? (
        <motion.span
          layoutId="top-nav-active-underline"
          className="absolute inset-x-3 bottom-0 h-0.5 rounded-pill bg-brand-600"
          transition={{ duration: 0.18, ease: [0.4, 0, 0.6, 1] }}
        />
      ) : null}
    </button>
  );
}

export function TopNav() {
  const [tab, setTab] = useTab();

  return (
    <header className="sticky top-0 z-30 border-b border-ink-300/15 bg-card/90 shadow-card backdrop-blur">
      <div className="mx-auto grid min-h-16 max-w-7xl grid-cols-[1fr_auto_1fr] items-center gap-4 px-5">
        <div className="flex min-w-0 items-center gap-3">
          <LogoMark />
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-ink-900">Invoice Archive AI</div>
          </div>
        </div>

        <nav className="flex items-center gap-1 rounded-card bg-ink-300/10 p-1" aria-label="Primary tabs">
          {tabOrder.map((item) => (
            <TopNavTab key={item} tab={item} active={item === tab} onSelect={setTab} />
          ))}
        </nav>

        <div aria-hidden="true" />
      </div>
    </header>
  );
}
