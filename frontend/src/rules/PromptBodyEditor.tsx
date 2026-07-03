import { memo, useEffect, useState } from "react";

type PromptBodyEditorProps = {
  tag: string;
  value: string;
  disabled?: boolean;
  onCommit: (value: string) => void;
};

export default memo(function PromptBodyEditor({
  tag,
  value,
  disabled = false,
  onCommit
}: PromptBodyEditorProps) {
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    setDraft(value);
  }, [tag, value]);

  return (
    <section className="flex min-h-[440px] flex-1 flex-col rounded-card border border-ink-300/15 bg-ink-300/[0.03] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-ink-900">Prompt Body</h3>
          <p className="mt-1 text-xs leading-5 text-ink-500">Synced to the rule draft on blur only; typing does not refresh the full page.</p>
        </div>
      </div>
      <textarea
        value={draft}
        disabled={disabled}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => onCommit(draft)}
        placeholder="Enter variable recognition rules for this tag"
        className="mt-3 min-h-0 flex-1 resize-none rounded-card border border-ink-300/15 bg-white p-4 text-sm leading-6 text-ink-900 outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/15 disabled:bg-ink-300/5 disabled:text-ink-500"
      />
      <div className="mt-2 flex items-center justify-end text-xs text-ink-500">
        <span className="font-semibold">{draft.length.toLocaleString()} characters</span>
      </div>
    </section>
  );
});
