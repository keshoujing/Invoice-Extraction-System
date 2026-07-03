import { fieldAliases } from "./constants";

export function displayDate(value?: string | null): string {
  if (!value) return "";
  return value.replace("T", " ").replace("+00:00", "");
}

export function valueFor(data: Record<string, unknown>, key: string): string {
  const aliases = fieldAliases[key] || [key];
  for (const alias of aliases) {
    const value = data[alias];
    if (value !== undefined && value !== null) {
      if (typeof value === "object") return JSON.stringify(value, null, 2);
      return String(value);
    }
  }
  return "";
}

export function setValueFor(data: Record<string, unknown>, key: string, value: unknown): Record<string, unknown> {
  const next = { ...data };
  const aliases = fieldAliases[key] || [key];
  const existing = aliases.find((alias) => Object.prototype.hasOwnProperty.call(next, alias));
  return {
    ...next,
    [existing || key]: value
  };
}

export function todayInputValue(date = new Date()): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function dateTimeInputValue(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

export function defaultConfirmedTimeRange(): { from: string; to: string } {
  const end = new Date();
  const start = new Date(end.getTime() - 60 * 60 * 1000);
  return {
    from: dateTimeInputValue(start),
    to: dateTimeInputValue(end)
  };
}

export function dateTimeInputToUtcIso(value: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().replace(/\.\d{3}Z$/, "+00:00");
}

export function advanceStartNumber(startNumber: string, count: number): string {
  const start = Number.parseInt(startNumber || "0", 10);
  if (!Number.isFinite(start)) return startNumber;
  const width = Math.max(4, startNumber.length);
  return String(start + count).padStart(width, "0");
}

export function formatAmount(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = typeof value === "number"
    ? value
    : Number(String(value).replace(/[$,\s]/g, ""));
  if (!Number.isFinite(numeric)) return String(value);
  return numeric.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function fieldValueForDisplay(data: Record<string, unknown>, key: string): string {
  if (Object.prototype.hasOwnProperty.call(data, key)) {
    const value = data[key];
    if (value !== undefined && value !== null && typeof value === "object") return JSON.stringify(value, null, 2);
    return value === undefined || value === null ? "" : String(value);
  }
  return valueFor(data, key);
}
