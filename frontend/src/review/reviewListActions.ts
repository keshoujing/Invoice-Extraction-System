import type { Invoice } from "../types";

export type ReviewListAction = "retry" | "delete";

export function reviewListActionsForInvoice(invoice: Invoice): ReviewListAction[] {
  if (invoice.status === "failed") return ["retry", "delete"];
  if (invoice.status === "recognized") return ["delete"];
  return [];
}
