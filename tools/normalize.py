"""Arabic text normalization for search keys.

Preserves originals — normalization is only used to generate search keys.
"""

from __future__ import annotations

import re

# Harakat/diacritics, tatweel, and superscript alef.
_STRIP = re.compile(r"[\u064B-\u0652\u0670\u0640]")
_WS = re.compile(r"\s+")

# أ إ آ → ا ; ة → ه ; ى → ي
_ALEFS = str.maketrans({
    "\u0623": "\u0627",  # أ
    "\u0625": "\u0627",  # إ
    "\u0622": "\u0627",  # آ
    "\u0629": "\u0647",  # ة
    "\u0649": "\u064A",  # ى
})


def normalize_ar(text: str | None) -> str:
    if not text:
        return ""
    s = _STRIP.sub("", text)
    s = s.translate(_ALEFS)
    s = _WS.sub(" ", s).strip()
    return s


def normalize_en(text: str | None) -> str:
    if not text:
        return ""
    return _WS.sub(" ", text).strip().lower()


def search_keys(*parts: str | None) -> list[str]:
    """Build a deduped, ordered list of normalized search keys."""
    keys: list[str] = []
    seen: set[str] = set()
    for p in parts:
        for k in (normalize_ar(p), normalize_en(p)):
            if k and k not in seen:
                seen.add(k)
                keys.append(k)
    return keys