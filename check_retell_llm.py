"""Check Retell LLM config to find where tools are defined."""
import urllib.request
import json
import os

env_path = os.path.join(os.path.dirname(__file__), "backend", ".env")
env_vars = {}
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()

API_KEY = env_vars.get("RETELL_API_KEY", "")
LLM_ID = "llm_695fd3f8f2e5d577137e6d33ad44"

print(f"Fetching LLM config: {LLM_ID}")

req = urllib.request.Request(
    f"https://api.retellai.com/get-retell-llm/{LLM_ID}",
    headers={"Authorization": f"Bearer {API_KEY}"}
)
resp = urllib.request.urlopen(req, timeout=15)
llm = json.loads(resp.read())

print(f"LLM Model: {llm.get('model', 'N/A')}")
print(f"LLM Keys: {list(llm.keys())}")

# Check tools
tools = llm.get("tools", [])
functions = llm.get("functions", [])
print(f"\nTools ({len(tools)}):")
for t in tools:
    ttype = t.get("type", "N/A")
    name = t.get("name", "") or t.get("function", {}).get("name", "N/A")
    print(f"  - type={ttype}, name={name}")
    if ttype in ("custom", "webhook"):
        print(f"    url={t.get('url', 'N/A')}")
    desc = t.get("description", "") or t.get("function", {}).get("description", "")
    if desc:
        print(f"    desc={desc[:100]}")
    params = t.get("parameters", {}) or t.get("function", {}).get("parameters", {})
    if params:
        print(f"    params={json.dumps(params)[:200]}")

print(f"\nFunctions ({len(functions)}):")
for f in functions:
    print(f"  - {f.get('name', 'N/A')}")

# Print general_prompt
prompt = llm.get("general_prompt", "")
if prompt:
    print(f"\nGeneral Prompt (first 500 chars):")
    print(prompt[:500])

# Print full config for reference
print(f"\n--- Full LLM Config (truncated):")
print(json.dumps(llm, indent=2)[:3000])
