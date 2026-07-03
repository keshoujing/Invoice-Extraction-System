"""Download a subset of katanaml-org/invoices-donut-data-v1 as images + labels.

Reproduces both the committed demo set and the (gitignored) scoring set.

Examples:
    python evaluation/scripts/fetch_dataset.py --split test --n 20 \
        --out evaluation/invoices-donut-demo
    python evaluation/scripts/fetch_dataset.py --split train --n 100 \
        --out evaluation/scoring-set
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download
from PIL import Image

REPO = "katanaml-org/invoices-donut-data-v1"
SPLIT_FILES = {
    "test": "data/test-00000-of-00001-56af6bd5ff7eb34d.parquet",
    "validation": "data/validation-00000-of-00001-b8a5c4a6237baf25.parquet",
    "train": "data/train-00000-of-00001-a5c51039eab2980a.parquet",
}


def _image_bytes(field) -> bytes:
    if isinstance(field, dict):
        if field.get("bytes"):
            return field["bytes"]
        if field.get("path"):
            return Path(field["path"]).read_bytes()
    if isinstance(field, (bytes, bytearray)):
        return bytes(field)
    raise ValueError(f"unexpected image field type: {type(field)}")


def fetch(split: str, n: int, out: Path, labels_only: bool = False) -> int:
    parquet_path = hf_hub_download(repo_id=REPO, filename=SPLIT_FILES[split], repo_type="dataset")
    rows = pq.read_table(parquet_path).to_pylist()
    out.mkdir(parents=True, exist_ok=True)
    if not labels_only:
        (out / "images").mkdir(parents=True, exist_ok=True)

    manifest = []
    for i, row in enumerate(rows[:n], start=1):
        name = f"invoice_{i:03d}.png"
        if not labels_only:
            image = Image.open(io.BytesIO(_image_bytes(row["image"]))).convert("RGB")
            image.save(out / "images" / name)
        raw = row["ground_truth"]
        gt = json.loads(raw) if isinstance(raw, str) else raw
        manifest.append({"file": f"images/{name}", "ground_truth": gt})

    with (out / "ground_truth.jsonl").open("w", encoding="utf-8") as fh:
        for item in manifest:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    return len(manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=tuple(SPLIT_FILES), default="test")
    parser.add_argument("--n", type=int, default=20, help="number of samples to extract")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument("--labels-only", action="store_true", help="write ground_truth.jsonl only (skip images)")
    args = parser.parse_args()

    count = fetch(args.split, args.n, args.out, labels_only=args.labels_only)
    print(f"wrote {count} images + ground_truth.jsonl to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
