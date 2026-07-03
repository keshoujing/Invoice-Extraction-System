import { memo, useEffect, useState } from "react";

type PreviewPromptEditorProps = {
  schemeName: string;
  enabled: boolean;
  value: string;
  disabled?: boolean;
  onEnabledChange: (enabled: boolean) => void;
  onCommit: (value: string) => void;
};

export default memo(function PreviewPromptEditor({
  schemeName,
  enabled,
  value,
  disabled = false,
  onEnabledChange,
  onCommit
}: PreviewPromptEditorProps) {
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    setDraft(value);
  }, [schemeName, value]);

  return (
    <section className="rounded-card border border-ink-300/15 bg-ink-300/[0.03] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-ink-900">Preview Prompt</h3>
          <p className="mt-1 text-xs leading-5 text-ink-500">
            Write only short hints that help identify supplier and document type. When disabled, upload preview will not use this text.
          </p>
        </div>
        <label className="inline-flex cursor-pointer items-center gap-2 text-xs font-semibold text-ink-600">
          <span>{enabled ? "Enabled" : "Disabled"}</span>
          <input
            type="checkbox"
            checked={enabled}
            disabled={disabled}
            onChange={(event) => onEnabledChange(event.target.checked)}
            className="sr-only"
            aria-label="Enable Preview Prompt"
          />
          <span
            className={[
              "relative h-6 w-11 rounded-pill transition-colors",
              enabled ? "bg-brand-600" : "bg-ink-300/25",
              disabled ? "opacity-50" : ""
            ].filter(Boolean).join(" ")}
          >
            <span
              className={[
                "absolute left-1 top-1 size-4 rounded-full bg-white shadow-sm transition-transform",
                enabled ? "translate-x-5" : ""
              ].filter(Boolean).join(" ")}
            />
          </span>
        </label>
      </div>
      <textarea
        value={draft}
        disabled={disabled || !enabled}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => onCommit(draft)}
        placeholder={'For example: If the document shows "ENTRY SUMMARY" and "U.S. Customs and Border Protection", treat it as invoice-like for this workflow.'}
        className="mt-3 h-28 w-full resize-none rounded-card border border-ink-300/15 bg-white p-3 text-sm leading-6 text-ink-900 outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/15 disabled:bg-ink-300/5 disabled:text-ink-500"
      />
      <div className="mt-2 flex items-center justify-between text-xs text-ink-500">
        <span>Recommended length: 1-3 sentences. Avoid field extraction rules.</span>
        <span className="font-semibold">{draft.length.toLocaleString()} characters</span>
      </div>
    </section>
  );
});
