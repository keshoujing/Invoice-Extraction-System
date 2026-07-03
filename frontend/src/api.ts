import type {
  ActiveRecognition,
  ExportMode,
  ExportResult,
  ExportStats,
  ExportStatus,
  Invoice,
  PromptFieldConfig,
  PromptRulesImportResult,
  PromptRulesPayload,
  PromptTagExportSettings,
  RecognitionJob,
  Scheme,
  SupplierAutoArchiveConfig,
  SupplierAutoArchiveCheck,
  Supplier,
  UploadPreviewJob
} from "./types";

const API_BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = init?.body instanceof FormData
    ? init.headers
    : {
        "Content-Type": "application/json",
        ...((init?.headers || {}) as Record<string, string>)
      };
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const data = await response.json();
      message = data.detail || message;
    } catch {
      message = await response.text();
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function fileUrl(invoiceId: number): string {
  return `${API_BASE}/invoices/${invoiceId}/file`;
}

export async function uploadInvoices(files: FileList | File[]): Promise<UploadPreviewJob> {
  const form = new FormData();
  Array.from(files).forEach((file) => form.append("files", file));
  return request<UploadPreviewJob>("/invoices/upload", {
    method: "POST",
    body: form
  });
}

export async function getUploadPreviewJob(jobId: string): Promise<UploadPreviewJob> {
  return request<UploadPreviewJob>(`/upload-preview/jobs/${jobId}`);
}

export async function listInvoices(params: {
  status?: string;
  export_status?: ExportStatus;
  supplier?: string;
  expense_type?: string;
  category?: string;
  vendor_code?: string;
  vendor_name?: string;
  po_number?: string;
  invoice_number?: string;
  date_from?: string;
  date_to?: string;
  day?: string;
  confirmed_from?: string;
  confirmed_to?: string;
  amount_min?: string;
  amount_max?: string;
} = {}): Promise<Invoice[]> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) search.set(key, value);
  });
  const query = search.toString();
  return request<Invoice[]>(`/invoices${query ? `?${query}` : ""}`);
}

export async function listInvoiceCategories(): Promise<string[]> {
  return request<string[]>("/invoice-categories");
}

export async function getExportStats(): Promise<ExportStats> {
  return request<ExportStats>("/export-stats");
}

export async function listSuppliers(query = "", limit = 5000): Promise<Supplier[]> {
  const search = new URLSearchParams();
  if (query) search.set("q", query);
  search.set("limit", String(limit));
  return request<Supplier[]>(`/suppliers?${search.toString()}`);
}

export async function createSupplier(payload: { code: string; name: string }): Promise<Supplier> {
  return request<Supplier>("/suppliers", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function deleteSupplier(code: string): Promise<{ code: string; deleted: boolean }> {
  return request<{ code: string; deleted: boolean }>(`/suppliers/${encodeURIComponent(code)}`, {
    method: "DELETE"
  });
}

export async function getAutoArchiveActiveCodes(): Promise<string[]> {
  return request<string[]>("/suppliers/auto-archive-active");
}

export async function getSupplierAutoArchiveConfig(code: string): Promise<SupplierAutoArchiveConfig> {
  return request<SupplierAutoArchiveConfig>(`/suppliers/${encodeURIComponent(code)}/auto-archive-checks`);
}

export async function updateSupplierAutoArchiveConfig(
  code: string,
  checks: SupplierAutoArchiveCheck[]
): Promise<SupplierAutoArchiveConfig> {
  return request<SupplierAutoArchiveConfig>(`/suppliers/${encodeURIComponent(code)}/auto-archive-checks`, {
    method: "PUT",
    body: JSON.stringify({ checks })
  });
}

export async function listSchemes(): Promise<Scheme[]> {
  return request<Scheme[]>("/schemes");
}

export async function createScheme(payload: { name: string; inherit_from?: string }): Promise<Scheme> {
  return request<Scheme>("/schemes", {
    method: "POST",
    body: JSON.stringify({
      name: payload.name,
      inherit_from: payload.inherit_from ?? "default"
    })
  });
}

export async function updateScheme(
  name: string,
  payload: {
    name?: string;
    preview_prompt_body?: string;
    preview_prompt_enabled?: boolean;
    prompt_body?: string;
    fields?: PromptFieldConfig[];
    export_settings?: PromptTagExportSettings;
  }
): Promise<Scheme> {
  return request<Scheme>(`/schemes/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteScheme(name: string): Promise<{ name: string; deleted: boolean }> {
  return request<{ name: string; deleted: boolean }>(`/schemes/${encodeURIComponent(name)}`, {
    method: "DELETE"
  });
}

export async function listSupplierSchemeMap(): Promise<Record<string, string>> {
  return request<Record<string, string>>("/supplier-scheme-map");
}

export async function exportPromptRules(): Promise<PromptRulesPayload> {
  return request<PromptRulesPayload>("/prompt-rules/export");
}

export async function importPromptRules(
  payload: PromptRulesPayload,
  options: { override_stale?: boolean } = {}
): Promise<PromptRulesImportResult> {
  return request<PromptRulesImportResult>("/prompt-rules/import", {
    method: "POST",
    body: JSON.stringify({ payload, override_stale: Boolean(options.override_stale) })
  });
}

export async function assignSupplierScheme(code: string, schemeName: string): Promise<void> {
  await request<unknown>(`/supplier-scheme-map/${encodeURIComponent(code)}`, {
    method: "PUT",
    body: JSON.stringify({ scheme_name: schemeName })
  });
}

export async function clearSupplierScheme(code: string): Promise<void> {
  await request<unknown>(`/supplier-scheme-map/${encodeURIComponent(code)}`, {
    method: "DELETE"
  });
}

export async function startRecognition(invoiceIds: number[]): Promise<RecognitionJob> {
  return request<RecognitionJob>("/recognition/jobs", {
    method: "POST",
    body: JSON.stringify({ invoice_ids: invoiceIds })
  });
}

export async function getJob(jobId: string): Promise<RecognitionJob> {
  return request<RecognitionJob>(`/recognition/jobs/${jobId}`);
}

export async function getActiveRecognition(): Promise<ActiveRecognition> {
  return request<ActiveRecognition>("/recognition/active");
}

export async function getActiveUploadPreview(): Promise<UploadPreviewJob | null> {
  return request<UploadPreviewJob | null>("/upload-preview/active");
}

export async function retryInvoice(invoiceId: number): Promise<RecognitionJob> {
  return request<RecognitionJob>(`/invoices/${invoiceId}/retry`, {
    method: "POST"
  });
}

export async function retrySupplierPreview(invoiceId: number): Promise<Invoice> {
  return request<Invoice>(`/invoices/${invoiceId}/supplier-preview/retry`, {
    method: "POST"
  });
}

export async function deleteInvoice(invoiceId: number): Promise<{ id: number; deleted_file: boolean }> {
  return request<{ id: number; deleted_file: boolean }>(`/invoices/${invoiceId}`, {
    method: "DELETE"
  });
}

export async function saveExtractedData(
  invoiceId: number,
  extractedData: Record<string, unknown>,
  expenseType: string
): Promise<Invoice> {
  return request<Invoice>(`/invoices/${invoiceId}/extracted-data`, {
    method: "PATCH",
    body: JSON.stringify({
      extracted_data: extractedData,
      expense_type: expenseType
    })
  });
}

export async function saveManualEntry(
  invoiceId: number,
  extractedData: Record<string, unknown>,
  expenseType: string
): Promise<Invoice> {
  return request<Invoice>(`/invoices/${invoiceId}/manual-entry`, {
    method: "POST",
    body: JSON.stringify({
      extracted_data: extractedData,
      expense_type: expenseType
    })
  });
}

export async function confirmPendingSupplier(
  invoiceId: number,
  payload: { vendor_code?: string; vendor_name?: string }
): Promise<Invoice> {
  return request<Invoice>(`/invoices/${invoiceId}/supplier-confirm`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function persistExtractedDataInBackground(
  invoiceId: number,
  extractedData: Record<string, unknown>,
  expenseType: string
): void {
  void fetch(`${API_BASE}/invoices/${invoiceId}/extracted-data`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      extracted_data: extractedData,
      expense_type: expenseType
    }),
    keepalive: true
  }).catch(() => undefined);
}

export async function confirmInvoice(invoiceId: number): Promise<Invoice> {
  return request<Invoice>(`/invoices/${invoiceId}/confirm`, {
    method: "POST"
  });
}

export async function selectDirectory(): Promise<{ path?: string | null; canceled: boolean }> {
  return request<{ path?: string | null; canceled: boolean }>("/system/select-directory", {
    method: "POST"
  });
}

export async function exportArchive(payload: {
  destination_dir: string;
  prefix: string;
  start_number: string;
  invoice_ids: number[];
  create_new_folder: boolean;
  filters: {
    mode: ExportMode;
    export_status?: ExportStatus;
    day?: string;
    date_from?: string;
    date_to?: string;
    confirmed_from?: string;
    confirmed_to?: string;
    supplier?: string;
    category?: string;
  };
}): Promise<ExportResult> {
  return request<ExportResult>("/exports/excel", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}
