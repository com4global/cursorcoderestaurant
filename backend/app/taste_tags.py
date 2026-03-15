"""
Item tagging for taste profile and recommendations.
Derives tags from dish name, cuisine, protein_type (rule-based; no LLM).
"""
from __future__ import annotations

import json
import re
from typing import List

# Keywords in item name → tags
NAME_TAG_PATTERNS = [
    (re.compile(r"\bbiryani\b", re.I), "biryani"),
    (re.compile(r"\bcurry\b|\bmasala\b|\bkorma\b|\bvindaloo\b", re.I), "curry"),
    (re.compile(r"\btikka\b|\btandoori\b", re.I), "tandoor"),
    (re.compile(r"\bnaan\b|\broti\b|\bparatha\b|\bkulcha\b", re.I), "bread"),
    (re.compile(r"\bchicken\b", re.I), "chicken"),
    (re.compile(r"\blamb\b|\bmutton\b", re.I), "lamb"),
    (re.compile(r"\bpaneer\b|\btofu\b", re.I), "vegetarian"),
    (re.compile(r"\bveg\b|\bvegetarian\b|\bvegan\b", re.I), "vegetarian"),
    (re.compile(r"\bspicy\b|\bhot\b|\bchilli\b|\bmirch\b", re.I), "spicy"),
    (re.compile(r"\bmild\b", re.I), "mild"),
    (re.compile(r"\brice\b|\bpulao\b|\bfried rice\b", re.I), "rice"),
    (re.compile(r"\bsoup\b", re.I), "soup"),
    (re.compile(r"\bsalad\b", re.I), "salad"),
    (re.compile(r"\bdessert\b|\bsweet\b|\bkheer\b|\bgulab\b|\bjalebi\b", re.I), "dessert"),
    (re.compile(r"\bdrink\b|\blassi\b|\bchai\b|\bjuice\b", re.I), "beverage"),
]


def derive_item_tags(
    name: str | None,
    cuisine: str | None,
    protein_type: str | None,
) -> List[str]:
    """Build a list of tags from item name, cuisine, and protein_type (no DB/LLM)."""
    tags = set()
    text = " ".join(filter(None, [name or "", cuisine or "", protein_type or ""]))
    if not text.strip():
        return []
    text_lower = text.lower()
    for pattern, tag in NAME_TAG_PATTERNS:
        if pattern.search(text):
            tags.add(tag)
    if cuisine:
        tags.add(cuisine.strip().lower().replace(" ", "-"))
    if protein_type:
        p = protein_type.strip().lower()
        if p in ("veg", "vegetarian", "vegan"):
            tags.add("vegetarian")
        else:
            tags.add(p.replace(" ", "-"))
    return sorted(tags)
