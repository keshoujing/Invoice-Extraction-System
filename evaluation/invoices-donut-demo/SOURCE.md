# Demo invoice dataset — attribution

These 20 sample invoices (synthetic) are a subset of the **test** split of:

- **Dataset:** `katanaml-org/invoices-donut-data-v1`
- **URL:** https://huggingface.co/datasets/katanaml-org/invoices-donut-data-v1
- **License:** MIT

All seller/buyer names, tax IDs, and amounts are synthetically generated and
contain no real company or personal data. Used here as a public, reproducible
demo/eval set for the invoice-extraction pipeline.

`ground_truth.jsonl` preserves the original Donut-format labels
(`header` / `items` / `summary`) so the set can be scored against.
