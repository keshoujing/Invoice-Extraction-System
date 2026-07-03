import * as Tabs from "@radix-ui/react-tabs";
import { lazy, Suspense, useEffect, useState } from "react";
import type { Scheme } from "../types";
import { Badge, StatusDot } from "../ui/Badge";
import { Button } from "../ui/Button";
import { SpinnerPanel } from "../ui/Spinner";
import type { SchemeDraft } from "./useSchemes";

const PromptBodyEditor = lazy(() => import("./PromptBodyEditor"));
const PreviewPromptEditor = lazy(() => import("./PreviewPromptEditor"));
const FieldsEditor = lazy(() => import("./FieldsEditor"));
const ExportColumnsEditor = lazy(() => import("./ExportColumnsEditor"));

const tabClass = [
  "rounded-soft px-3 py-2 text-sm font-semibold text-ink-500 outline-none transition-colors duration-fast",
  "hover:bg-brand-50 hover:text-brand-700",
  "data-[state=active]:bg-brand-50 data-[state=active]:text-brand-700"
].join(" ");

const panelClass = [
  "mt-4 min-h-[480px] rounded-card border border-ink-300/10 bg-white p-4 outline-none",
  "data-[state=inactive]:animate-out data-[state=inactive]:fade-out data-[state=inactive]:duration-micro",
  "data-[state=active]:animate-in data-[state=active]:fade-in data-[state=active]:duration-fast"
].join(" ");

type Props = {
  scheme: Scheme | null;
  draft: SchemeDraft;
  saving: boolean;
  hasUnsavedChanges: boolean;
  onDraftChange: (patch: Partial<SchemeDraft> | ((draft: SchemeDraft) => SchemeDraft)) => void;
  onSave: () => Promise<void>;
  onDelete: (scheme: Scheme) => Promise<void>;
};

export function SchemeEditor({
  scheme,
  draft,
  saving,
  hasUnsavedChanges,
  onDraftChange,
  onSave,
  onDelete
}: Props) {
  const [nameDraft, setNameDraft] = useState(draft.name);

  useEffect(() => {
    setNameDraft(draft.name);
  }, [draft.name, scheme?.name]);

  if (!scheme) {
    return (
      <section className="grid min-h-[640px] flex-1 place-items-center rounded-card border border-dashed border-ink-300/20 bg-card text-sm text-ink-500 shadow-card">
        Select a scheme to view or edit
      </section>
    );
  }

  return (
    <section className="flex min-h-[640px] flex-1 flex-col rounded-card border border-ink-300/10 bg-card shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-ink-300/10 p-5">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <input
              value={nameDraft}
              disabled={scheme.is_default || saving}
              onChange={(event) => setNameDraft(event.target.value)}
              onBlur={() => {
                const next = scheme.is_default ? scheme.name : nameDraft.trim();
                setNameDraft(next);
                onDraftChange({ name: next });
              }}
              className="min-w-0 max-w-md rounded-soft border border-transparent bg-transparent px-2 py-1 text-lg font-semibold text-ink-900 outline-none transition focus:border-brand-500 focus:bg-white focus:ring-2 focus:ring-brand-500/15 disabled:opacity-100"
              aria-label="Scheme name"
            />
            {scheme.is_default ? <Badge>Default</Badge> : null}
          </div>
          <p className="mt-1 text-sm text-ink-500">
            Fields {draft.fields.length} · Used by {scheme.supplier_count} suppliers · {draft.export_settings.custom ? "Custom export columns" : "default export columns"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-2 rounded-pill bg-ink-300/10 px-2.5 py-1 text-xs font-semibold text-ink-500">
            <StatusDot variant={saving ? "warn" : hasUnsavedChanges ? "warn" : "ok"} />
            {saving ? "Saving" : hasUnsavedChanges ? "Unsaved" : "Saved"}
          </span>
          <Button variant="primary" className="min-h-9 px-3 py-1.5 text-sm" disabled={!hasUnsavedChanges || saving} onClick={() => void onSave()}>
            Save
          </Button>
          {!scheme.is_default ? (
            <Button variant="danger" className="min-h-9 px-3 py-1.5 text-sm" disabled={saving} onClick={() => void onDelete(scheme)}>
              Delete
            </Button>
          ) : null}
        </div>
      </div>

      <Tabs.Root defaultValue="prompt" className="min-h-0 flex-1 p-5">
        <Tabs.List className="inline-flex rounded-card border border-ink-300/10 bg-ink-300/5 p-1">
          <Tabs.Trigger value="prompt" className={tabClass}>Prompt</Tabs.Trigger>
          <Tabs.Trigger value="fields" className={tabClass}>Fields</Tabs.Trigger>
          <Tabs.Trigger value="export" className={tabClass}>Export Columns</Tabs.Trigger>
        </Tabs.List>

        <Suspense fallback={<SpinnerPanel label="Loading editor" />}>
          <Tabs.Content value="prompt" className={panelClass}>
            <div className="flex h-full min-h-[440px] flex-col gap-4">
              <PreviewPromptEditor
                schemeName={scheme.name}
                enabled={draft.preview_prompt_enabled}
                value={draft.preview_prompt_body}
                disabled={saving}
                onEnabledChange={(preview_prompt_enabled) => onDraftChange({ preview_prompt_enabled })}
                onCommit={(preview_prompt_body) => onDraftChange({ preview_prompt_body })}
              />
              <PromptBodyEditor
                tag={scheme.name}
                value={draft.prompt_body}
                disabled={saving}
                onCommit={(prompt_body) => onDraftChange({ prompt_body })}
              />
            </div>
          </Tabs.Content>
          <Tabs.Content value="fields" className={panelClass}>
            <FieldsEditor
              fields={draft.fields}
              disabled={saving}
              onChange={(fields) => onDraftChange({ fields })}
            />
          </Tabs.Content>
          <Tabs.Content value="export" className={panelClass}>
            <ExportColumnsEditor
              fields={draft.fields}
              settings={draft.export_settings}
              disabled={saving}
              onChange={(export_settings) => onDraftChange({ export_settings })}
            />
          </Tabs.Content>
        </Suspense>
      </Tabs.Root>
    </section>
  );
}
