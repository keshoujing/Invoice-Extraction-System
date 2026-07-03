from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..config import SUPPLIER_FILE


try:
    from rapidfuzz import fuzz, process
except ImportError:  # pragma: no cover - fallback keeps the app importable before deps are installed.
    fuzz = None
    process = None


@dataclass(frozen=True)
class SupplierMatch:
    code: str
    name: str
    matched: bool
    confidence: float = 0.0
    method: str = "none"
    query: str = ""


@dataclass(frozen=True)
class SupplierRecord:
    code: str
    name: str


def _load_suppliers_from_db() -> list[tuple[str, str]]:
    from app.database import db_cursor

    with db_cursor() as cur:
        rows = cur.execute("SELECT code, name FROM suppliers ORDER BY code").fetchall()
    return [(str(row["code"]), str(row["name"])) for row in rows]


def normalize_str(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").split())


class SupplierMatcher:
    def __init__(
        self,
        supplier_file: Path = SUPPLIER_FILE,
        source: Callable[[], list[tuple[str, str]]] | None = None,
    ) -> None:
        self.supplier_file = supplier_file
        self._source = source
        self._rebuild()

    def reload(self) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        self.suppliers = [
            (normalize_str(code), normalize_str(name))
            for code, name in self._load()
            if normalize_str(code) and normalize_str(name)
        ]
        self.names_lower = [item[1].lower() for item in self.suppliers]
        self.by_code = {code.lower(): SupplierRecord(code, name) for code, name in self.suppliers}
        self.by_name = {name.lower(): SupplierRecord(code, name) for code, name in self.suppliers}
        self._tokens_cache: dict[int, set[str]] = {}
        self._core_tokens_cache: dict[int, set[str]] = {}
        for idx, (_, name) in enumerate(self.suppliers):
            tokens = self._tokens(name)
            self._tokens_cache[idx] = tokens
            self._core_tokens_cache[idx] = self._core_tokens(tokens)

    _GENERIC_COMPANY_TOKENS = {
        "company",
        "co",
        "corp",
        "corporation",
        "inc",
        "incorporated",
        "llc",
        "ltd",
        "limited",
        "plc",
        "sa",
        "ag",
        "pte",
        "group",
        "holding",
        "holdings",
        "international",
        "intl",
        "trading",
        "services",
        "service",
        "solutions",
        "solution",
        "technology",
        "tech",
        "industrial",
        "industries",
        "material",
        "materials",
        "systems",
        "system",
    }

    def _tokens(self, value: str) -> set[str]:
        normalized = normalize_str(value).lower()
        # Keep alnum/word chunks (works for latin letters, digits and CJK words).
        return {token for token in re.findall(r"\w+", normalized, flags=re.UNICODE) if token}

    def _core_tokens(self, tokens: set[str]) -> set[str]:
        return {
            token
            for token in tokens
            if token not in self._GENERIC_COMPANY_TOKENS and not token.isdigit() and len(token) >= 2
        }

    def _composite_score(self, query: str, query_tokens: set[str], query_core_tokens: set[str], idx: int) -> float:
        name_lower = self.names_lower[idx]
        supplier_tokens = self._tokens_cache[idx]
        supplier_core_tokens = self._core_tokens_cache[idx]

        set_score = float(fuzz.token_set_ratio(query, name_lower)) / 100.0 if fuzz is not None else 0.0
        sort_score = float(fuzz.token_sort_ratio(query, name_lower)) / 100.0 if fuzz is not None else 0.0

        shared_tokens = query_tokens & supplier_tokens
        shared_core_tokens = query_core_tokens & supplier_core_tokens
        core_overlap_ratio = (
            float(len(shared_core_tokens)) / float(len(query_core_tokens))
            if query_core_tokens
            else 0.0
        )

        # Combined score: lower weight on token_set_ratio to reduce generic-word inflation.
        score = (set_score * 0.45) + (sort_score * 0.40) + (core_overlap_ratio * 0.15)

        # Penalize matches that only overlap on generic legal words like "corporation".
        if query_core_tokens and supplier_core_tokens and not shared_core_tokens:
            score -= 0.35
        elif shared_tokens and not shared_core_tokens:
            score -= 0.20

        if score < 0.0:
            return 0.0
        if score > 1.0:
            return 1.0
        return score

    def _load(self) -> list[tuple[str, str]]:
        if self._source is not None:
            return self._source()
        try:
            return _load_suppliers_from_db()
        except sqlite3.OperationalError:
            return self._load_from_file()

    def _load_from_file(self) -> list[tuple[str, str]]:
        if not self.supplier_file.exists():
            return []
        lines = self.supplier_file.read_text(encoding="utf-8").splitlines()
        suppliers: list[tuple[str, str]] = []
        for line in lines[1:]:
            parts = line.strip().split("\t")
            if len(parts) < 2:
                continue
            code = normalize_str(parts[0])
            name = normalize_str(parts[1])
            if code and name:
                suppliers.append((code, name))
        return suppliers

    def list(self) -> list[SupplierRecord]:
        return [SupplierRecord(code, name) for code, name in self.suppliers]

    def search(self, query: str = "", limit: int = 200) -> list[SupplierRecord]:
        clean = normalize_str(query).lower()
        records = self.list()
        if clean:
            records = [
                item
                for item in records
                if clean in item.code.lower() or clean in item.name.lower()
            ]
        return records[:limit]

    def get_by_code(self, code: str) -> SupplierRecord | None:
        return self.by_code.get(normalize_str(code).lower())

    def get_by_name(self, name: str) -> SupplierRecord | None:
        return self.by_name.get(normalize_str(name).lower())

    def resolve_exact(self, code: str, name: str) -> SupplierRecord | None:
        clean_code = normalize_str(code)
        clean_name = normalize_str(name)
        if not clean_code and not clean_name:
            return None

        supplier_by_code = self.get_by_code(clean_code) if clean_code else None
        supplier_by_name = self.get_by_name(clean_name) if clean_name else None

        if clean_code and not supplier_by_code:
            raise ValueError("Vendor code is not in the supplier library")
        if clean_name and not supplier_by_name:
            raise ValueError("Vendor name is not in the supplier library")
        if supplier_by_code and supplier_by_name and supplier_by_code.code != supplier_by_name.code:
            raise ValueError("Vendor code and vendor name do not match")

        return supplier_by_code or supplier_by_name

    def top_matches(self, raw_name: str, limit: int = 3) -> list[SupplierMatch]:
        clean = normalize_str(raw_name)
        if not clean:
            return []
        if not self.suppliers:
            return []

        clean_lower = clean.lower()
        for code, name in self.suppliers:
            if clean_lower == name.lower():
                return [SupplierMatch(code, name, True, 1.0, "exact", clean)]

        if process is not None and fuzz is not None:
            query_tokens = self._tokens(clean_lower)
            query_core_tokens = self._core_tokens(query_tokens)
            shortlist_size = max(max(1, limit) * 8, 24)
            results = process.extract(
                clean_lower,
                self.names_lower,
                scorer=fuzz.token_set_ratio,
                limit=shortlist_size,
            )
            rescored: list[tuple[float, int]] = []
            for result in results:
                if len(result) >= 3:
                    _matched_name, _score, idx = result[0], result[1], int(result[2])
                else:
                    matched_name = result[0]
                    idx = self.names_lower.index(matched_name)
                score = self._composite_score(clean_lower, query_tokens, query_core_tokens, idx)
                rescored.append((score, idx))

            rescored.sort(key=lambda item: item[0], reverse=True)
            matches: list[SupplierMatch] = []
            used_codes: set[str] = set()
            for score, idx in rescored:
                code, name = self.suppliers[idx]
                if code in used_codes:
                    continue
                used_codes.add(code)
                matches.append(
                    SupplierMatch(
                        code=code,
                        name=name,
                        matched=False,
                        confidence=float(score),
                        method="fuzzy_core",
                        query=clean,
                    )
                )
                if len(matches) >= max(1, limit):
                    break
            return matches

        return []

    def best_match(self, raw_name: str) -> SupplierMatch:
        clean = normalize_str(raw_name)
        if not clean:
            return SupplierMatch("", "", False, 0.0, "none", "")
        if not self.suppliers:
            return SupplierMatch("", clean, False, 0.0, "none", clean)

        matches = self.top_matches(clean, limit=1)
        if matches:
            return matches[0]
        return SupplierMatch("", clean, False, 0.0, "none", clean)

    def match(self, raw_name: str, threshold: float = 0.8) -> SupplierMatch:
        best = self.best_match(raw_name)
        if not best.code:
            return best
        return SupplierMatch(
            best.code,
            best.name,
            best.confidence >= threshold,
            best.confidence,
            best.method,
            best.query,
        )
