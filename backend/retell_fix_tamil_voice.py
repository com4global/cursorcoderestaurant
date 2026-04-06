"""Fix Tamil agent: update voice + update Retell LLM prompt with dynamic variable."""
import httpx
import json
import os

from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("RETELL_API_KEY")
TAMIL_AGENT_ID = os.getenv("AI_CALL_PROVIDER_AGENT_ID_TA") or "agent_1944b97877da59c9ca44108683"
LLM_ID = "llm_695fd3f8f2e5d577137e6d33ad44"
BASE = "https://api.retellai.com"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

# Step 1: Update Tamil agent voice to Indian female (Monika)
print(f"Updating Tamil agent {TAMIL_AGENT_ID} voice to 11labs-Monika (Indian female)...")
resp = httpx.patch(
    f"{BASE}/update-agent/{TAMIL_AGENT_ID}",
    json={"voice_id": "11labs-Monika"},
    headers=HEADERS, timeout=15,
)
resp.raise_for_status()
updated = resp.json()
print(f"  Voice updated to: {updated.get('voice_id')}")
print(f"  Language: {updated.get('language')}")

# Step 2: Get current LLM prompt
print(f"\nFetching LLM {LLM_ID}...")
resp = httpx.get(f"{BASE}/get-retell-llm/{LLM_ID}", headers=HEADERS, timeout=15)
resp.raise_for_status()
llm = resp.json()
old_prompt = llm.get("general_prompt", "")
print(f"  Current prompt (first 200 chars): {old_prompt[:200]}")

# Step 3: Replace hardcoded English instruction with dynamic variable
# The hardcoded line is: "Respond in English suitable for Indian restaurant ordering calls."
new_prompt = old_prompt.replace(
    "Respond in English suitable for Indian restaurant ordering calls.",
    "{{language_instruction}}"
)

if new_prompt == old_prompt:
    # If exact match not found, prepend the variable
    print("  WARNING: Could not find exact English instruction to replace.")
    print("  Prepending {{language_instruction}} to prompt...")
    new_prompt = "{{language_instruction}}\n" + old_prompt

print(f"\n  Updated prompt (first 300 chars): {new_prompt[:300]}")

# Step 4: Update the LLM
print(f"\nUpdating LLM {LLM_ID}...")
resp = httpx.patch(
    f"{BASE}/update-retell-llm/{LLM_ID}",
    json={"general_prompt": new_prompt},
    headers=HEADERS, timeout=15,
)
resp.raise_for_status()
updated_llm = resp.json()
print(f"  LLM prompt updated successfully.")
print(f"  Updated prompt (first 300 chars): {updated_llm.get('general_prompt', '')[:300]}")

print("\n=== DONE ===")
print("1. Tamil agent voice: 11labs-Monika (Indian female)")
print("2. LLM prompt: {{language_instruction}} replaces hardcoded English instruction")
print("3. Backend sends Tanglish instruction for ta-IN, English for en-IN")
print("Restart backend and test!")
