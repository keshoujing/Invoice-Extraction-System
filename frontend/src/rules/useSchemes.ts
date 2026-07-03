import { useCallback, useEffect, useMemo, useState } from "react";
import { createScheme, deleteScheme, listSchemes, updateScheme } from "../api";
import type { PromptFieldConfig, PromptTagExportSettings, Scheme } from "../types";

const DEFAULT_SCHEME_NAME = "default";

export interface SchemeDraft {
  name: string;
  preview_prompt_body: string;
  preview_prompt_enabled: boolean;
  prompt_body: string;
  fields: PromptFieldConfig[];
  export_settings: PromptTagExportSettings;
}

function schemeToDraft(scheme: Scheme): SchemeDraft {
  return {
    name: scheme.name,
    preview_prompt_body: scheme.preview_prompt_body,
    preview_prompt_enabled: scheme.preview_prompt_enabled,
    prompt_body: scheme.prompt_body,
    fields: scheme.fields,
    export_settings: scheme.export_settings
  };
}

function emptyDraft(): SchemeDraft {
  return {
    name: "",
    preview_prompt_body: "",
    preview_prompt_enabled: false,
    prompt_body: "",
    fields: [],
    export_settings: { custom: false, columns: [] }
  };
}

function isEqualDraft(a: SchemeDraft, b: SchemeDraft): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function useSchemes() {
  const [schemes, setSchemes] = useState<Scheme[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [selectedName, setSelectedName] = useState(DEFAULT_SCHEME_NAME);
  const [drafts, setDrafts] = useState<Record<string, SchemeDraft>>({});

  const refresh = useCallback(async (preferName?: string) => {
    setLoading(true);
    try {
      const next = await listSchemes();
      setSchemes(next);
      setDrafts((previous) => {
        const output: Record<string, SchemeDraft> = {};
        next.forEach((scheme) => {
          const existing = previous[scheme.name];
          output[scheme.name] = existing && existing.name === scheme.name ? existing : schemeToDraft(scheme);
        });
        return output;
      });
      setSelectedName((current) => {
        if (preferName && next.some((scheme) => scheme.name === preferName)) return preferName;
        if (next.some((scheme) => scheme.name === current)) return current;
        return next[0]?.name ?? DEFAULT_SCHEME_NAME;
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const selectedScheme = useMemo(
    () => schemes.find((scheme) => scheme.name === selectedName) ?? null,
    [schemes, selectedName]
  );

  const selectedDraft = drafts[selectedName] ?? (selectedScheme ? schemeToDraft(selectedScheme) : emptyDraft());

  const hasUnsavedChanges = useMemo(() => {
    if (!selectedScheme) return false;
    return !isEqualDraft(selectedDraft, schemeToDraft(selectedScheme));
  }, [selectedDraft, selectedScheme]);

  const updateDraft = useCallback((
    patch: Partial<SchemeDraft> | ((draft: SchemeDraft) => SchemeDraft)
  ) => {
    setDrafts((previous) => {
      const current = previous[selectedName] ?? (selectedScheme ? schemeToDraft(selectedScheme) : null);
      if (!current) return previous;
      const next = typeof patch === "function" ? patch(current) : { ...current, ...patch };
      return { ...previous, [selectedName]: next };
    });
  }, [selectedName, selectedScheme]);

  const createNew = useCallback(async (name: string, inheritFrom: string) => {
    setSaving(true);
    try {
      const created = await createScheme({ name, inherit_from: inheritFrom });
      await refresh(created.name);
      return created;
    } finally {
      setSaving(false);
    }
  }, [refresh]);

  const save = useCallback(async () => {
    if (!selectedScheme) return null;
    const draft = drafts[selectedName];
    if (!draft) return null;
    setSaving(true);
    try {
      const updated = await updateScheme(selectedScheme.name, {
        name: draft.name !== selectedScheme.name ? draft.name : undefined,
        preview_prompt_body: draft.preview_prompt_body,
        preview_prompt_enabled: draft.preview_prompt_enabled,
        prompt_body: draft.prompt_body,
        fields: draft.fields,
        export_settings: draft.export_settings
      });
      await refresh(updated.name);
      return updated;
    } finally {
      setSaving(false);
    }
  }, [drafts, refresh, selectedName, selectedScheme]);

  const remove = useCallback(async (name: string) => {
    setSaving(true);
    try {
      await deleteScheme(name);
      await refresh();
    } finally {
      setSaving(false);
    }
  }, [refresh]);

  return {
    schemes,
    loading,
    saving,
    selectedScheme,
    selectedName,
    selectedDraft,
    selectName: setSelectedName,
    refresh,
    updateDraft,
    createScheme: createNew,
    saveScheme: save,
    deleteScheme: remove,
    hasUnsavedChanges
  };
}
