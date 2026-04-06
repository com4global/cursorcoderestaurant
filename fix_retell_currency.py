"""Update Retell LLM prompt to use Rupees instead of dollars."""
import os, httpx, json, sys
from pathlib import Path

# Load env
env_path = Path(__file__).parent / "backend" / ".env"
env_vars = {}
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()

API_KEY = env_vars.get("RETELL_API_KEY", "")
ENG_AGENT = env_vars.get("AI_CALL_PROVIDER_AGENT_ID_EN", "")
TAMIL_AGENT = env_vars.get("AI_CALL_PROVIDER_AGENT_ID_TA", "")
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

def get_llm_id(agent_id):
    r = httpx.get(f"https://api.retellai.com/get-agent/{agent_id}", headers=HEADERS, timeout=15)
    r.raise_for_status()
    agent = r.json()
    return agent.get("response_engine", {}).get("llm_id", "")

def update_llm_prompt(llm_id, label):
    r = httpx.get(f"https://api.retellai.com/get-retell-llm/{llm_id}", headers=HEADERS, timeout=15)
    r.raise_for_status()
    llm = r.json()
    prompt = llm.get("general_prompt", "")
    print(f"\n=== {label} LLM ({llm_id}) ===")
    print(f"Full prompt:\n{prompt}\n---END---")

    # Replace dollar references with rupee references
    new_prompt = prompt

    # Fix any garbled "never Rupees" from previous run
    new_prompt = new_prompt.replace("never Rupees", "never dollars")

    # Make price instruction more explicit
    old_price = "Convert cents to rupees when reading prices."
    new_price = "Prices are in Indian Rupees (\u20b9). Convert cents to rupees naturally (e.g. 1599 cents = \u20b9159.99). Always say rupees, never dollars."
    new_prompt = new_prompt.replace(old_price, new_price)

    if new_prompt != prompt:
        print(f"Updating prompt...")
        r2 = httpx.patch(
            f"https://api.retellai.com/update-retell-llm/{llm_id}",
            json={"general_prompt": new_prompt},
            headers=HEADERS,
            timeout=15,
        )
        r2.raise_for_status()
        print(f"Updated! New snippet: ...{new_prompt[200:600]}...")
    else:
        print("No dollar references found in prompt, no changes needed.")

for label, agent_id in [("English", ENG_AGENT), ("Tamil", TAMIL_AGENT)]:
    if not agent_id:
        print(f"Skipping {label} — no agent ID configured.")
        continue
    llm_id = get_llm_id(agent_id)
    if not llm_id:
        print(f"Skipping {label} — no LLM ID found.")
        continue
    update_llm_prompt(llm_id, label)

print("\nDone!")
