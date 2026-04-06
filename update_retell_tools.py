"""Update Retell LLM tool URLs to use the per-tool endpoint."""
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
BACKEND_URL = "https://backend-iota-navy-64.vercel.app"

# 1. Fetch current LLM config
req = urllib.request.Request(
    f"https://api.retellai.com/get-retell-llm/{LLM_ID}",
    headers={"Authorization": f"Bearer {API_KEY}"}
)
resp = urllib.request.urlopen(req, timeout=15)
llm = json.loads(resp.read())

print("Current tools:")
for t in llm.get("general_tools", []):
    print(f"  {t.get('name')}: {t.get('url')}")

# 2. Update each tool URL to the per-tool endpoint
updated_tools = []
for tool in llm.get("general_tools", []):
    name = tool.get("name", "")
    new_url = f"{BACKEND_URL}/api/call-order/realtime/retell-tool/{name}"
    tool["url"] = new_url
    updated_tools.append(tool)

# 3. PATCH the LLM with updated tools
patch_data = json.dumps({"general_tools": updated_tools}).encode()
patch_req = urllib.request.Request(
    f"https://api.retellai.com/update-retell-llm/{LLM_ID}",
    data=patch_data,
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    },
    method="PATCH",
)
patch_resp = urllib.request.urlopen(patch_req, timeout=15)
result = json.loads(patch_resp.read())

print("\nUpdated tools:")
for t in result.get("general_tools", []):
    print(f"  {t.get('name')}: {t.get('url')}")

print("\nDone! All tool URLs updated to per-tool endpoints.")
