import { memo, useEffect, useMemo, useState } from "react";
import type { PromptFieldConfig } from "../types";
import { Button } from "../ui/Button";
import { Badge } from "../ui/Badge";
import { fieldGroupOptions, fixedVendorField } from "../lib/constants";
import {
  emptyPromptChildField,
  emptyPromptField,
  ensureFixedPromptFields,
  fieldPathId,
  flattenPromptFields,
  getFieldAtPath,
  inferFieldGroup,
  isFixedVendorField,
  normalizeFieldGroup,
  removeFieldAtPath,
  updateFieldAtPath
} from "../lib/prompt";

type FieldsEditorProps = {
  fields: PromptFieldConfig[];
  disabled?: boolean;
  onChange: (fields: PromptFieldConfig[]) => void;
};

type FieldRowProps = {
  field: PromptFieldConfig;
  path: number[];
  depth: number;
  disabled: boolean;
  onCommit: (path: number[], patch: Partial<PromptFieldConfig>) => void;
  onAddChild: (index: number) => void;
  onRemove: (path: number[]) => void;
  onRemoveChildren: (index: number) => void;
};

function patchField(field: PromptFieldConfig, path: number[], patch: Partial<PromptFieldConfig>) {
  if (isFixedVendorField(field.key)) return { ...fixedVendorField };
  const nextType = patch.type || field.type;
  const next: PromptFieldConfig = { ...field, ...patch };
  const previousInferredGroup = inferFieldGroup(field.key, field.type);

  if (path.length > 1 && (nextType === "array" || nextType === "fixed")) next.type = "string";
  if (next.type !== "array") delete next.children;
  if (next.type === "array") next.children = next.children || [];
  if (next.type !== "fixed") delete next.value;
  if (next.type === "fixed") next.examples = "";

  if (path.length > 1) {
    next.group = "line_items";
  } else if (!patch.group && (patch.key !== undefined || patch.type !== undefined)) {
    const currentGroup = normalizeFieldGroup(field.group, field.key, field.type);
    next.group = !field.group || currentGroup === previousInferredGroup
      ? inferFieldGroup(next.key, next.type)
      : currentGroup;
  } else {
    next.group = normalizeFieldGroup(next.group, next.key, next.type);
  }
  return next;
}

const FieldRow = memo(function FieldRow({
  field,
  path,
  depth,
  disabled,
  onCommit,
  onAddChild,
  onRemove,
  onRemoveChildren
}: FieldRowProps) {
  const locked = isFixedVendorField(field.key);
  const child = depth > 0;
  const [draft, setDraft] = useState(field);

  useEffect(() => {
    setDraft(field);
  }, [field]);

  function commit(patch: Partial<PromptFieldConfig>) {
    setDraft((current) => ({ ...current, ...patch }));
    onCommit(path, patch);
  }

  return (
    <tr className={locked ? "bg-brand-50/60" : "hover:bg-brand-50/40"}>
      <td className="w-[30%] px-3 py-3 align-top">
        <div className="flex items-start gap-2" style={{ paddingLeft: depth ? 22 : 0 }}>
          {child ? <span className="mt-2 text-ink-300">↳</span> : null}
          <div className="min-w-0 flex-1">
            <input
              value={draft.key}
              disabled={disabled || locked}
              onChange={(event) => setDraft((current) => ({ ...current, key: event.target.value }))}
              onBlur={() => commit({ key: draft.key })}
              placeholder={child ? "BOL_number" : "invoice_number"}
              className="w-full rounded-soft border border-ink-300/15 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/15 disabled:bg-ink-300/5"
            />
            <div className="mt-1 flex flex-wrap gap-1">
              {locked ? <Badge>Fixed</Badge> : null}
              {field.type === "array" ? <Badge variant="neutral">list</Badge> : null}
              {field.type === "fixed" ? <Badge variant="neutral">Fixed Value</Badge> : null}
            </div>
          </div>
        </div>
      </td>
      <td className="px-3 py-3 align-top">
        <select
          value={normalizeFieldGroup(draft.group, draft.key, draft.type)}
          disabled={disabled || locked || child}
          onChange={(event) => commit({ group: event.target.value })}
          className="w-full rounded-soft border border-ink-300/15 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500"
        >
          {fieldGroupOptions.map((group) => (
            <option key={group.value} value={group.value}>{group.label}</option>
          ))}
        </select>
      </td>
      <td className="px-3 py-3 align-top">
        <select
          value={draft.type}
          disabled={disabled || locked}
          onChange={(event) => commit({ type: event.target.value as PromptFieldConfig["type"] })}
          className="w-full rounded-soft border border-ink-300/15 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500"
        >
          <option value="string">string</option>
          <option value="value">value</option>
          <option value="bool">bool</option>
          {!child ? <option value="array">array</option> : null}
          {!child ? <option value="fixed">fixed</option> : null}
        </select>
      </td>
      <td className="px-3 py-3 align-top">
        {locked ? (
          <span className="text-xs font-medium text-ink-500">Filled from the supplier confirmed in Pending</span>
        ) : draft.type === "fixed" ? (
          <input
            value={draft.value || ""}
            disabled={disabled}
            onChange={(event) => setDraft((current) => ({ ...current, value: event.target.value }))}
            onBlur={() => commit({ value: draft.value || "" })}
            placeholder="For example: raw material"
            className="w-full rounded-soft border border-ink-300/15 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500"
          />
        ) : (
          <textarea
            value={draft.examples || ""}
            disabled={disabled}
            onChange={(event) => setDraft((current) => ({ ...current, examples: event.target.value }))}
            onBlur={() => commit({ examples: draft.examples || "" })}
            placeholder="Examples, one per line or comma-separated"
            rows={2}
            className="w-full resize-y rounded-soft border border-ink-300/15 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500"
          />
        )}
      </td>
      <td className="px-3 py-3 align-top">
        {locked ? (
          <span className="text-xs font-semibold text-ink-500">Cannot delete</span>
        ) : (
          <div className="flex flex-wrap gap-2">
            {field.type === "array" && !child ? (
              <>
                <Button className="min-h-8 px-2.5 py-1.5 text-xs" onClick={() => onAddChild(path[0])} disabled={disabled}>Child Field</Button>
                <Button className="min-h-8 px-2.5 py-1.5 text-xs" variant="danger" onClick={() => onRemoveChildren(path[0])} disabled={disabled || !field.children?.length}>Clear All</Button>
              </>
            ) : null}
            <Button className="min-h-8 px-2.5 py-1.5 text-xs" variant="danger" onClick={() => onRemove(path)} disabled={disabled}>Delete</Button>
          </div>
        )}
      </td>
    </tr>
  );
});

export default function FieldsEditor({ fields, disabled = false, onChange }: FieldsEditorProps) {
  const normalizedFields = useMemo(() => ensureFixedPromptFields(fields), [fields]);
  const rows = useMemo(() => flattenPromptFields(normalizedFields), [normalizedFields]);

  function changeFields(next: PromptFieldConfig[]) {
    onChange(ensureFixedPromptFields(next));
  }

  function handleCommit(path: number[], patch: Partial<PromptFieldConfig>) {
    changeFields(updateFieldAtPath(normalizedFields, path, (field) => patchField(field, path, patch)));
  }

  function handleAddField() {
    changeFields([...normalizedFields, emptyPromptField()]);
  }

  function handleAddChild(index: number) {
    changeFields(normalizedFields.map((field, fieldIndex) => (
      fieldIndex === index && field.type === "array"
        ? { ...field, children: [...(field.children || []), emptyPromptChildField()] }
        : field
    )));
  }

  function handleRemove(path: number[]) {
    const field = getFieldAtPath(normalizedFields, path);
    if (!field || isFixedVendorField(field.key)) return;
    const label = field.key.trim() || (path.length > 1 ? "this child field" : "this field");
    if (!window.confirm(`Delete "${label}"?`)) return;
    changeFields(removeFieldAtPath(normalizedFields, path));
  }

  function handleRemoveChildren(index: number) {
    const field = normalizedFields[index];
    if (!field?.children?.length) return;
    if (!window.confirm(`Delete "${field.key || "the current array field"}" child fields?`)) return;
    changeFields(normalizedFields.map((item, fieldIndex) => (
      fieldIndex === index ? { ...item, children: [] } : item
    )));
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink-900">Return Fields</h3>
          <p className="text-xs text-ink-500">Fixed supplier fields always stay first and are normalized on save.</p>
        </div>
        <Button onClick={handleAddField} disabled={disabled}>+ Add Field</Button>
      </div>
      <div className="overflow-auto rounded-card border border-ink-300/10">
        <table className="min-w-[920px] w-full divide-y divide-ink-300/15 text-left">
          <thead className="bg-ink-300/5 text-xs font-semibold text-ink-500">
            <tr>
              <th className="px-3 py-2">Key</th>
              <th className="px-3 py-2">Group</th>
              <th className="px-3 py-2">Type</th>
              <th className="px-3 py-2">Examples / Fixed Value</th>
              <th className="px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-300/10 bg-white">
            {rows.map((row) => (
              <FieldRow
                key={fieldPathId(row.path)}
                disabled={disabled}
                onCommit={handleCommit}
                onAddChild={handleAddChild}
                onRemove={handleRemove}
                onRemoveChildren={handleRemoveChildren}
                {...row}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
