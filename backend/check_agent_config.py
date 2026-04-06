"""Check Retell agent and LLM configuration."""
import httpx
import os
import json
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("RETELL_API_KEY")
BASE = "https://api.retellai.com"
HEADERS = {"Authorization": f"Bearer {api_key}"}

# Tamil agent
agent_id_ta = os.getenv("AI_CALL_PROVIDER_AGENT_ID_TA")
r = httpx.get(f"{BASE}/get-agent/{agent_id_ta}", headers=HEADERS, timeout=15)
d = r.json()
print("=== Tamil Agent ===")
print("voice_id:", d.get("voice_id"))
print("language:", d.get("language"))
print("agent_name:", d.get("agent_name"))

# English agent
agent_id_en = os.getenv("AI_CALL_PROVIDER_AGENT_ID_EN")
r2 = httpx.get(f"{BASE}/get-agent/{agent_id_en}", headers=HEADERS, timeout=15)
d2 = r2.json()
print("\n=== English Agent ===")
print("voice_id:", d2.get("voice_id"))
print("language:", d2.get("language"))
print("agent_name:", d2.get("agent_name"))

# Tamil LLM
llm_id = d.get("response_engine", {}).get("llm_id")
if llm_id:
    r3 = httpx.get(f"{BASE}/get-retell-llm/{llm_id}", headers=HEADERS, timeout=15)
    d3 = r3.json()
    print("\n=== Tamil LLM ===")
    print("llm_id:", llm_id)
    print("model:", d3.get("model"))
    prompt = d3.get("general_prompt", "")
    print("prompt (first 800 chars):")
    print(prompt[:800])
    print("\ngeneral_tools:")
    for t in d3.get("general_tools", []):
        print(f"  - {t.get('name')}: {t.get('url', '')[:80]}")
