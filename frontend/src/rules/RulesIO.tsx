import { useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { exportPromptRules, importPromptRules } from "../api";
import type { PromptRulesImportResult, PromptRulesPayload } from "../types";
import { promptRulesDownloadName, promptRulesImportNotice } from "../lib/prompt";
import { Button } from "../ui/Button";

type RulesIOProps = {
  hasUnsavedChanges: boolean;
  disabled?: boolean;
  onImported: () => Promise<void>;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
};

function isPromptRulesPayload(value: unknown): value is PromptRulesPayload {
  return Boolean(
    value
      && typeof value === "object"
      && (value as PromptRulesPayload).schema === "invoice-archive.prompt-rules"
      && (
        Array.isArray((value as PromptRulesPayload).schemes)
        || Array.isArray((value as PromptRulesPayload).tags)
      )
  );
}

export function RulesIO({
  hasUnsavedChanges,
  disabled = false,
  onImported,
  onSuccess,
  onError
}: RulesIOProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);

  function reportImportResult(result: PromptRulesImportResult) {
    const skipped = [...result.skipped_supplier_codes, ...result.skipped_mappings];
    onSuccess(skipped.length
      ? `${promptRulesImportNotice(result)}；${skipped.slice(0, 3).join(", ")}`
      : promptRulesImportNotice(result)
    );
  }

  async function handleExport() {
    if (hasUnsavedChanges && !window.confirm("The current scheme has unsaved changes. Export will use the saved rules. Continue?")) return;
    setBusy(true);
    try {
      const payload = await exportPromptRules();
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = promptRulesDownloadName(payload);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      onSuccess("Configuration exported");
    } catch (error) {
      onError(error instanceof Error ? error.message : "Configuration export failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleImportFile(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0];
    input.value = "";
    if (!file) return;
    if (hasUnsavedChanges && !window.confirm("The current scheme has unsaved changes. Import will refresh the rule list. Continue?")) return;
    setBusy(true);
    try {
      const parsed = JSON.parse(await file.text()) as unknown;
      if (!isPromptRulesPayload(parsed)) {
        throw new Error("Choose a valid configuration export file");
      }
      const result = await importPromptRules(parsed);
      await onImported();
      reportImportResult(result);
      if (result.stale_conflicts.length) {
        const shouldOverride = window.confirm(
          `The import file has ${result.stale_conflicts.length} items older than the current database configuration and they were skipped. Force overwrite the newer local configuration?`
        );
        if (shouldOverride) {
          const overrideResult = await importPromptRules(parsed, { override_stale: true });
          await onImported();
          reportImportResult(overrideResult);
        }
      }
    } catch (error) {
      onError(error instanceof Error ? error.message : "Configuration load failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-1.5">
        <Button
          className="min-h-9 px-2.5 py-1.5 text-xs"
          disabled={disabled || busy}
          onClick={() => inputRef.current?.click()}
        >
          Load Configuration
        </Button>
        <Button
          className="min-h-9 px-2.5 py-1.5 text-xs"
          disabled={disabled || busy}
          onClick={() => void handleExport()}
        >
          Export Configuration
        </Button>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="application/json,.json"
        className="hidden"
        onChange={(event) => void handleImportFile(event)}
      />
    </>
  );
}
