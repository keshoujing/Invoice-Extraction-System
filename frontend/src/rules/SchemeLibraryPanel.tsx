import type { Scheme } from "../types";
import { Badge } from "../ui/Badge";

type Props = {
  schemes: Scheme[];
  selectedName: string;
  onSelect: (name: string) => void;
  onCreate: () => void;
};

export function SchemeLibraryPanel({ schemes, selectedName, onSelect, onCreate }: Props) {
  return (
    <aside className="flex h-[640px] w-[280px] shrink-0 flex-col rounded-card border border-ink-300/10 bg-card shadow-card">
      <div className="flex items-center justify-between border-b border-ink-300/10 px-4 py-3">
        <h3 className="text-sm font-semibold text-ink-900">Scheme Library</h3>
        <button
          type="button"
          onClick={onCreate}
          className="rounded-soft px-2 py-1 text-xs font-semibold text-brand-700 hover:bg-brand-50"
        >
          + New
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {schemes.map((scheme) => {
          const active = scheme.name === selectedName;
          return (
            <button
              key={scheme.name}
              type="button"
              onClick={() => onSelect(scheme.name)}
              className={[
                "flex w-full items-center justify-between gap-2 border-b border-ink-300/5 px-4 py-3 text-left text-sm transition-colors",
                active ? "bg-brand-50 font-semibold text-brand-700" : "hover:bg-ink-300/5"
              ].join(" ")}
            >
              <span className="min-w-0 truncate">{scheme.name}</span>
              <span className="flex shrink-0 items-center gap-1">
                {scheme.is_default ? <Badge>Default</Badge> : null}
                <Badge variant="neutral">{scheme.supplier_count}</Badge>
              </span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
