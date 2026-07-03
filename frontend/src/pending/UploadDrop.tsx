import { useRef, useState } from "react";
import { Button } from "../ui/Button";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.webp";

type UploadDropProps = {
  disabled?: boolean;
  isEmpty: boolean;
  onFiles: (files: FileList | File[]) => void;
};

export function UploadDrop({ disabled = false, isEmpty, onFiles }: UploadDropProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const expanded = dragActive || isEmpty;

  function handleFiles(files: FileList | null) {
    if (!files?.length || disabled) return;
    onFiles(files);
  }

  function handleDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(false);
    handleFiles(event.dataTransfer.files);
  }

  return (
    <div
      className={["relative", disabled ? "opacity-60" : ""].join(" ")}
      onDragEnter={(event) => {
        event.preventDefault();
        if (!disabled) setDragActive(true);
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={(event) => {
        if (event.currentTarget.contains(event.relatedTarget as Node)) return;
        setDragActive(false);
      }}
      onDrop={handleDrop}
    >
      <input
        ref={inputRef}
        className="sr-only"
        type="file"
        multiple
        accept={ACCEPT}
        disabled={disabled}
        onChange={(event) => {
          handleFiles(event.target.files);
          event.currentTarget.value = "";
        }}
      />

      <button
        type="button"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        className={[
          "w-full rounded-card border border-dashed border-ink-300/35 bg-white/70 px-4 text-left shadow-card",
          "transition-colors duration-fast ease-std hover:border-brand-500/60 hover:bg-brand-50/60",
          dragActive ? "border-brand-500/70 bg-brand-50/70" : "",
          expanded ? "min-h-24 py-4" : "min-h-10 py-2 pr-24"
        ].join(" ")}
      >
        <span className={["flex items-center gap-3", expanded ? "justify-center" : "justify-between"].join(" ")}>
          <span className="flex min-w-0 items-center gap-3">
            <span className="inline-grid size-8 shrink-0 place-items-center rounded-pill bg-brand-50 text-base font-bold text-brand-700">↑</span>
            <span className="block min-w-0">
              <span className="block text-sm font-semibold text-ink-900">
                {dragActive ? "Release to Upload" : isEmpty ? "Drop invoice files here" : "Drop files here"}
              </span>
              <span className="block text-xs text-ink-500">PDF, PNG, JPG, TIFF, and WEBP are supported; multiple files allowed</span>
            </span>
          </span>
        </span>
      </button>

      {dragActive ? (
        <div className="fixed inset-0 z-30 grid place-items-center bg-brand-50/85 backdrop-blur-sm transition-colors duration-fast" aria-hidden="true">
          <div className="rounded-card border border-dashed border-brand-500 bg-card px-10 py-8 text-center shadow-cardH">
            <p className="text-base font-semibold text-ink-900">Release to Upload</p>
            <p className="mt-1 text-sm text-ink-500">Supplier preview starts automatically after upload</p>
          </div>
        </div>
      ) : null}

      {!isEmpty ? (
        <Button
          className="absolute right-3 top-1/2 hidden -translate-y-1/2 sm:inline-flex"
          variant="ghost"
          disabled={disabled}
          onClick={(event) => {
            event.stopPropagation();
            inputRef.current?.click();
          }}
        >
          Upload
        </Button>
      ) : null}
    </div>
  );
}
