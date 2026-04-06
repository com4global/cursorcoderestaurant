"""Revert Retell LLM prompt to use dollars instead of rupees."""
import httpx
import os
from dotenv import load_dotenv

load_dotenv()
load_dotenv("backend/.env")
load_dotenv(".env")

API_KEY = os.getenv("RETELL_API_KEY")
LLM_ID = "llm_695fd3f8f2e5d577137e6d33ad44"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

r = httpx.get(f"https://api.retellai.com/get-retell-llm/{LLM_ID}", headers=HEADERS, timeout=15)
r.raise_for_status()
llm = r.json()
prompt = llm.get("general_prompt", "")

new_prompt = (
    prompt
    .replace("Indian Rupees", "dollars")
    .replace("rupees", "dollars")
    .replace("₹", "$")
    .replace("1599 cents = $159.99", "1599 cents = $15.99")
    .replace("1599 cents = $159", "1599 cents = $15.99")
    .replace("Always say dollars, never dollars", "Always say dollars, never rupees")
)

if new_prompt != prompt:
    r2 = httpx.patch(
        f"https://api.retellai.com/update-retell-llm/{LLM_ID}",
        json={"general_prompt": new_prompt},
        headers=HEADERS,
        timeout=15,
    )
    r2.raise_for_status()
    print("Retell LLM prompt updated to use dollars")
    for line in new_prompt.split("."):
        if "dollar" in line.lower() or "cent" in line.lower():
            print(f"  -> {line.strip()}")
else:
    print("No rupee references found in prompt")
    # Show currency-related lines
    for line in prompt.split("."):
        if any(w in line.lower() for w in ["dollar", "cent", "price", "rupee", "currency"]):
            print(f"  current: {line.strip()}")
