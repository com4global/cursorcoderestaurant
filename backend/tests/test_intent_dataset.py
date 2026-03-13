"""
Layer 1: JSON-Driven Intent Dataset Tests.

Loads intent_test_dataset.json and automatically validates
each test case against the intent extractor.
This catches regressions when regex patterns change.
"""
import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.intent_extractor import extract_intent_local


# ── Load dataset ─────────────────────────────────────────────────────────
DATASET_PATH = os.path.join(os.path.dirname(__file__), "intent_test_dataset.json")

with open(DATASET_PATH, "r") as f:
    TEST_CASES = json.load(f)

# Build pytest ids for readable output
CASE_IDS = [f"{c['id']}:{c['input'][:40]}" for c in TEST_CASES]


# ── Parametrized test ────────────────────────────────────────────────────
@pytest.mark.parametrize("case", TEST_CASES, ids=CASE_IDS)
def test_intent_extraction(case):
    """Validate that extract_intent_local produces the expected fields."""
    result = extract_intent_local(case["input"])
    expected = case["expected"]

    for field, expected_value in expected.items():
        actual_value = getattr(result, field, None)

        # For string fields, do case-insensitive comparison
        if isinstance(expected_value, str) and isinstance(actual_value, str):
            assert actual_value.lower() == expected_value.lower(), (
                f"[{case['id']}] '{case['input']}' → "
                f"{field}: expected '{expected_value}', got '{actual_value}'"
            )
        # For dish_name, allow substring match (e.g., "chicken biryani" contains "biryani")
        elif field == "dish_name" and isinstance(expected_value, str) and isinstance(actual_value, str):
            assert expected_value.lower() in actual_value.lower(), (
                f"[{case['id']}] '{case['input']}' → "
                f"{field}: expected '{expected_value}' to be in '{actual_value}'"
            )
        else:
            assert actual_value == expected_value, (
                f"[{case['id']}] '{case['input']}' → "
                f"{field}: expected {expected_value}, got {actual_value}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
