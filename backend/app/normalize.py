"""Normalization helpers for DOIs, titles and list-valued fields."""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

_DOI_URL_PREFIX = re.compile(
    r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*|doi\s+)", re.IGNORECASE
)
_WHITESPACE = re.compile(r"[\s​‌‍﻿]+")
_PUNCT = re.compile(r"[^0-9a-z一-鿿 ]+")
_CJK_SPACE = re.compile(r"(?<=[一-鿿])\s+(?=[一-鿿])")
_MULTISPACE = re.compile(r"\s+")


def normalize_doi(raw: str | None) -> str | None:
    """Strip resolver prefixes and whitespace, then lowercase.

    Matching is exact on the normalized value; no fuzzy DOI matching.
    """
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    # Prefixes may be stacked ("https://doi.org/doi:10....").
    for _ in range(3):
        new_value = _DOI_URL_PREFIX.sub("", value).strip()
        if new_value == value:
            break
        value = new_value
    value = _WHITESPACE.sub("", value).lower()
    return value or None


def normalize_title(raw: str | None) -> str:
    if raw is None:
        return ""
    value = unicodedata.normalize("NFKC", str(raw)).lower().strip()
    value = _PUNCT.sub(" ", value)
    value = _MULTISPACE.sub(" ", value).strip()
    # CJK has no word spaces; drop them so "图 神经网络" matches "图神经网络".
    return _CJK_SPACE.sub("", value)


def title_tokens(raw: str | None) -> set[str]:
    return set(normalize_title(raw).split())


def split_list(raw: Any) -> list[str]:
    """Parse a CSV/JSONL field that may be a list or a delimited string."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        items = [str(item).strip() for item in raw]
    else:
        text = str(raw).strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    items = [str(item).strip() for item in parsed]
                else:
                    items = [text]
            except json.JSONDecodeError:
                items = re.split(r"[;,|]", text)
        else:
            items = re.split(r"[;,|]", text)
    seen: list[str] = []
    for item in items:
        item = str(item).strip()
        if item and item not in seen:
            seen.append(item)
    return seen


def parse_year(raw: Any) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    match = re.search(r"(1[5-9]\d\d|20\d\d|21\d\d)", text)
    return int(match.group(1)) if match else None
