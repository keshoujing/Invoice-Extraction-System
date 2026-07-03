"""Build a synthetic supplier master from the dataset's seller strings.

The ground-truth `seller` bundles company name + address (e.g.
"Bradley-Andrade 9879 Elizabeth Common ..."). We parse the company-name portion
so the master mirrors what the extraction step actually returns (name only), and
assign each distinct supplier a synthetic vendor code.

This lets us evaluate supplier *identification* accuracy: given an invoice, does
the pipeline resolve it to the correct vendor_code?
"""
from __future__ import annotations

import re

# Address / mailing markers that follow the company name in the synthetic data.
_ADDRESS_MARKERS = r"\b(?:Unit|Suite|Ste|Apt|Box|USNV|USNS|USS|USCGC|FPO|APO|DPO)\b"


def parse_company_name(seller: str) -> str:
    """Extract the company-name portion from a `name + address` seller string."""
    s = str(seller or "").strip()
    match = re.search(r"\s\d", s)  # cut at the first street number
    if match:
        s = s[: match.start()]
    s = re.split(_ADDRESS_MARKERS, s)[0]
    return s.strip().rstrip(",").strip()


def build_master(sellers: list[str], start_code: int = 50001) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """Return (master, expected_by_name).

    master: list of (vendor_code, company_name), one per distinct company.
    expected_by_name: {company_name_lower: vendor_code} for expected-answer lookup.
    """
    master: list[tuple[str, str]] = []
    by_name: dict[str, str] = {}
    code = start_code
    for seller in sellers:
        name = parse_company_name(seller)
        if not name:
            continue
        key = name.lower()
        if key in by_name:
            continue
        vendor_code = str(code)
        by_name[key] = vendor_code
        master.append((vendor_code, name))
        code += 1
    return master, by_name


def expected_code(seller: str, by_name: dict[str, str]) -> str:
    """The vendor_code the pipeline should return for this seller."""
    return by_name.get(parse_company_name(seller).lower(), "")
