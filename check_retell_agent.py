"""Check and configure Retell agent tool definitions via their API."""
import urllib.request
import json
import os
import sys

# Load from .env
env_path = os.path.join(os.path.dirname(__file__), "backend", ".env")
env_vars = {}
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()

API_KEY = env_vars.get("RETELL_API_KEY", "")
AGENT_ID = env_vars.get("AI_CALL_PROVIDER_AGENT_ID", "") or env_vars.get("AI_CALL_PROVIDER_AGENT_ID_EN", "")
BACKEND_URL = "https://backend-iota-navy-64.vercel.app"

print(f"API Key: {API_KEY[:12]}...")
print(f"Agent ID: {AGENT_ID}")

# Get current agent config
req = urllib.request.Request(
    f"https://api.retellai.com/get-agent/{AGENT_ID}",
    headers={"Authorization": f"Bearer {API_KEY}"}
)
resp = urllib.request.urlopen(req, timeout=15)
agent = json.loads(resp.read())

print(f"\nAgent Name: {agent.get('agent_name', 'N/A')}")
print(f"LLM WebSocket URL: {agent.get('llm_websocket_url', 'N/A')}")
print(f"Response Engine: {agent.get('response_engine', {})}")

# Check tools
tools = agent.get("tools", [])
functions = agent.get("functions", [])
print(f"\nTools ({len(tools)}):")
for t in tools:
    print(f"  - type={t.get('type')}, name={t.get('name', t.get('function', {}).get('name', 'N/A'))}")
    if t.get("type") == "custom":
        print(f"    url={t.get('url', 'N/A')}")
    print(f"    full: {json.dumps(t, indent=4)[:500]}")

print(f"\nFunctions ({len(functions)}):")
for f in functions:
    print(f"  - {f.get('name', 'N/A')}: {json.dumps(f)[:200]}")

# Print full config for debugging
print(f"\n--- Full Agent Config Keys: {list(agent.keys())}")
