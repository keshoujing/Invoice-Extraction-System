from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class InvoiceOut(BaseModel):
    id: int
    original_filename: str
    stored_filename: str
    file_path: str
    mime_type: str
    status: str
    uploaded_at: str
    recognized_at: str | None = None
    confirmed_at: str | None = None
    updated_at: str
    error_message: str | None = None
    vendor_code: str = ""
    vendor_name: str = ""
    po_number: str = ""
    invoice_number: str = ""
    invoice_date: str = ""
    invoice_date_iso: str = ""
    total_amount: float = 0
    expense_type: str = ""
    invoice_category: str = ""
    archive_number: str | None = None
    exported_filename: str | None = None
    exported_path: str | None = None
    export_batch_id: str | None = None
    exported_at: str | None = None
    extracted_data: dict[str, Any] = Field(default_factory=dict)


class RecognitionRequest(BaseModel):
    invoice_ids: list[int]


class AutoArchiveSupplierSummary(BaseModel):
    vendor_code: str = ""
    vendor_name: str = ""
    count: int = 0


class RecognitionJobOut(BaseModel):
    id: str
    status: str
    total: int
    processed: int
    succeeded: int
    failed_count: int
    created_at: str
    updated_at: str
    error_message: str | None = None
    auto_archived_by_supplier: list[AutoArchiveSupplierSummary] = Field(default_factory=list)


class UploadPreviewJobOut(BaseModel):
    id: str
    status: str
    total: int
    processed: int
    succeeded: int
    failed_count: int
    created_at: str
    updated_at: str
    error_message: str | None = None
    invoices: list[InvoiceOut] = Field(default_factory=list)


class ActiveRecognitionOut(BaseModel):
    job: RecognitionJobOut | None = None
    invoice_ids: list[int] = Field(default_factory=list)


class UpdateExtractedDataRequest(BaseModel):
    extracted_data: dict[str, Any] = Field(default_factory=dict)
    expense_type: str = ""


class SupplierConfirmRequest(BaseModel):
    vendor_code: str = ""
    vendor_name: str = ""


class ExportFilters(BaseModel):
    mode: Literal["all", "day", "range", "supplier", "category"] = "all"
    export_status: Literal["unexported", "exported", "all"] = "unexported"
    day: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    confirmed_from: str | None = None
    confirmed_to: str | None = None
    supplier: str | None = None
    category: str | None = None


class ExportRequest(BaseModel):
    destination_dir: str
    prefix: str
    start_number: str = "0001"
    filters: ExportFilters = Field(default_factory=ExportFilters)
    invoice_ids: list[int] = Field(default_factory=list)
    create_new_folder: bool = False


class ExportOut(BaseModel):
    batch_id: str
    item_count: int
    destination_dir: str
    excel_path: str
    files: list[dict[str, str]]


class ExportStatsOut(BaseModel):
    confirmed_count: int
    exported_count: int
    unexported_count: int


class DirectorySelectionOut(BaseModel):
    path: str | None = None
    canceled: bool = False


class DeleteInvoiceOut(BaseModel):
    id: int
    deleted_file: bool = False


class SupplierOut(BaseModel):
    code: str
    name: str


class SupplierCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)


class SupplierAutoArchiveCheck(BaseModel):
    field_key: str
    baseline_value: str = ""
    tolerance_percent: str = ""
    enabled: bool = True


class SupplierAutoArchiveConfigOut(BaseModel):
    vendor_code: str
    vendor_name: str = ""
    scheme_name: str = ""
    available_fields: list[str] = Field(default_factory=list)
    checks: list[SupplierAutoArchiveCheck] = Field(default_factory=list)


class SupplierAutoArchiveConfigUpdate(BaseModel):
    checks: list[SupplierAutoArchiveCheck] = Field(default_factory=list)


class PromptTagExportColumn(BaseModel):
    key: str
    label: str = ""
    enabled: bool = True
    source: Literal["scalar", "array_child"] = "scalar"
    row_mode: Literal["merge", "repeat", "split_even"] = "repeat"
    array_key: str = ""
    child_key: str = ""
    type: str = "string"


class PromptTagExportSettings(BaseModel):
    custom: bool = False
    columns: list[PromptTagExportColumn] = Field(default_factory=list)


class PromptFieldConfig(BaseModel):
    key: str
    type: str = "string"
    group: str = ""
    examples: str = ""
    value: str = ""
    children: list[PromptFieldConfig] = Field(default_factory=list)


class PromptTagOut(BaseModel):
    tag: str
    prompt_body: str
    fields: list[PromptFieldConfig] = Field(default_factory=list)
    export_settings: PromptTagExportSettings = Field(default_factory=PromptTagExportSettings)
    is_default: bool = False
    supplier_count: int = 0
    updated_at: str


class PromptTagCreateRequest(BaseModel):
    tag: str
    prompt_body: str = ""
    fields: list[PromptFieldConfig] = Field(default_factory=list)
    export_settings: PromptTagExportSettings | None = None


class PromptTagUpdateRequest(BaseModel):
    tag: str | None = None
    prompt_body: str | None = None
    fields: list[PromptFieldConfig] | None = None
    export_settings: PromptTagExportSettings | None = None


class PromptTagSuppliersRequest(BaseModel):
    vendor_codes: list[str] = Field(default_factory=list)


class PromptTagDeleteOut(BaseModel):
    tag: str
    deleted: bool = False


class SchemeOut(BaseModel):
    name: str
    preview_prompt_body: str = ""
    preview_prompt_enabled: bool = False
    prompt_body: str = ""
    fields: list[PromptFieldConfig] = Field(default_factory=list)
    export_settings: PromptTagExportSettings = Field(default_factory=PromptTagExportSettings)
    is_default: bool = False
    supplier_count: int = 0
    updated_at: str = ""


class SchemeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    inherit_from: str = "default"


class SchemeUpdate(BaseModel):
    name: str | None = None
    preview_prompt_body: str | None = None
    preview_prompt_enabled: bool | None = None
    prompt_body: str | None = None
    fields: list[PromptFieldConfig] | None = None
    export_settings: PromptTagExportSettings | None = None


class SupplierSchemeAssign(BaseModel):
    scheme_name: str = Field(min_length=1, max_length=40)


class SpecialDocumentRuleOut(BaseModel):
    vendor_code: str
    vendor_name: str
    prompt_body: str = ""
    fields: list[PromptFieldConfig] = Field(default_factory=list)
    is_active: bool = True
    updated_at: str


class SpecialDocumentRuleCreateRequest(BaseModel):
    vendor_code: str = ""
    vendor_name: str = ""
    prompt_body: str | None = None
    fields: list[PromptFieldConfig] | None = None
    is_active: bool = True


class SpecialDocumentRuleUpdateRequest(BaseModel):
    prompt_body: str | None = None
    fields: list[PromptFieldConfig] | None = None
    is_active: bool | None = None


class SpecialDocumentRuleDeleteOut(BaseModel):
    vendor_code: str
    deleted: bool = False


class PromptRulesTagItem(BaseModel):
    tag: str
    prompt_body: str = ""
    fields: list[PromptFieldConfig] = Field(default_factory=list)
    export_settings: PromptTagExportSettings = Field(default_factory=PromptTagExportSettings)
    is_default: bool = False
    updated_at: str = ""


class PromptRulesSupplierMapItem(BaseModel):
    vendor_code: str
    tag: str
    vendor_name: str = ""
    updated_at: str = ""


class PromptRulesSpecialDocumentRuleItem(BaseModel):
    vendor_code: str
    vendor_name: str = ""
    prompt_body: str = ""
    fields: list[PromptFieldConfig] = Field(default_factory=list)
    is_active: bool = True
    updated_at: str = ""


class PromptRulesSchemeItem(BaseModel):
    name: str
    preview_prompt_body: str = ""
    preview_prompt_enabled: bool = False
    prompt_body: str = ""
    fields: list[PromptFieldConfig] = Field(default_factory=list)
    export_settings: PromptTagExportSettings = Field(default_factory=PromptTagExportSettings)
    is_default: bool = False
    updated_at: str = ""


class PromptRulesSupplierSchemeItem(BaseModel):
    vendor_code: str
    scheme_name: str
    updated_at: str = ""


class PromptRulesSupplierItem(BaseModel):
    code: str
    name: str
    updated_at: str = ""


class PromptRulesAutoArchiveCheckItem(BaseModel):
    vendor_code: str
    field_key: str
    baseline_value: str = ""
    tolerance_percent: str = ""
    enabled: bool = True
    updated_at: str = ""


class PromptRulesExportOut(BaseModel):
    schema_name: Literal["invoice-archive.prompt-rules"] = Field(
        default="invoice-archive.prompt-rules",
        alias="schema",
    )
    version: int = 5
    exported_at: str
    suppliers: list[PromptRulesSupplierItem] = Field(default_factory=list)
    schemes: list[PromptRulesSchemeItem] = Field(default_factory=list)
    supplier_scheme_map: list[PromptRulesSupplierSchemeItem] = Field(default_factory=list)
    auto_archive_checks: list[PromptRulesAutoArchiveCheckItem] = Field(default_factory=list)
    tags: list[PromptRulesTagItem] = Field(default_factory=list)
    supplier_tag_map: list[PromptRulesSupplierMapItem] = Field(default_factory=list)
    special_document_rules: list[PromptRulesSpecialDocumentRuleItem] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class PromptRulesImportRequest(BaseModel):
    payload: PromptRulesExportOut
    override_stale: bool = False


class PromptRulesStaleConflict(BaseModel):
    kind: Literal[
        "tag",
        "supplier",
        "supplier_mapping",
        "special_document_rule",
        "scheme",
        "supplier_scheme_mapping",
        "auto_archive_check",
    ]
    key: str
    import_updated_at: str = ""
    local_updated_at: str = ""


class PromptRulesImportOut(BaseModel):
    suppliers_created: int = 0
    suppliers_updated: int = 0
    tags_created: int = 0
    tags_updated: int = 0
    supplier_mappings_imported: int = 0
    supplier_mappings_removed: int = 0
    auto_archive_checks_imported: int = 0
    special_document_rules_created: int = 0
    special_document_rules_updated: int = 0
    skipped_supplier_codes: list[str] = Field(default_factory=list)
    skipped_mappings: list[str] = Field(default_factory=list)
    stale_conflicts: list[PromptRulesStaleConflict] = Field(default_factory=list)
    stale_conflicts_skipped: int = 0
