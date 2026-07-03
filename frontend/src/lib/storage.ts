import type { ExportStatus } from "../types";
import { STORAGE_KEYS, Tab } from "./constants";

function storage(): Storage | null {
  if (typeof window === "undefined") return null;
  return window.localStorage;
}

export function storedTab(): Tab {
  const value = storage()?.getItem(STORAGE_KEYS.tab);
  return value === "review" || value === "confirmed" || value === "rules" || value === "pending" ? value : "pending";
}

export function storeTab(tab: Tab): void {
  storage()?.setItem(STORAGE_KEYS.tab, tab);
}

export function storedReviewId(): number | null {
  const value = storage()?.getItem(STORAGE_KEYS.selectedReviewId);
  if (!value) return null;
  const id = Number(value);
  return Number.isFinite(id) ? id : null;
}

export function storeReviewId(id: number | null): void {
  if (id === null) {
    storage()?.removeItem(STORAGE_KEYS.selectedReviewId);
    return;
  }
  storage()?.setItem(STORAGE_KEYS.selectedReviewId, String(id));
}

export function storedString(key: string, fallback: string): string {
  return storage()?.getItem(key) ?? fallback;
}

export function storeString(key: string, value: string): void {
  storage()?.setItem(key, value);
}

export function storedBool(key: string, fallback: boolean): boolean {
  const value = storage()?.getItem(key);
  if (value === null || value === undefined) return fallback;
  return value === "true";
}

export function storeBool(key: string, value: boolean): void {
  storage()?.setItem(key, String(value));
}

export function storedExportStatus(): ExportStatus {
  const value = storage()?.getItem(STORAGE_KEYS.exportStatus);
  return value === "exported" || value === "all" || value === "unexported" ? value : "unexported";
}

export function storeExportStatus(status: ExportStatus): void {
  storage()?.setItem(STORAGE_KEYS.exportStatus, status);
}
