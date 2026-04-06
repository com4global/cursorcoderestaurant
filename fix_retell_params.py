"""Remove session_id from Retell tool parameters - it comes from call metadata, not LLM args."""
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

# Fetch current config
req = urllib.request.Request(
    f"https://api.retellai.com/get-retell-llm/{LLM_ID}",
    headers={"Authorization": f"Bearer {API_KEY}"}
)
resp = urllib.request.urlopen(req, timeout=15)
llm = json.loads(resp.read())

# Remove session_id from tool parameters
for tool in llm.get("general_tools", []):
    params = tool.get("parameters", {})
    props = params.get("properties", {})
    required = params.get("required", [])
    
    if "session_id" in props:
        del props["session_id"]
        print(f"  Removed session_id from {tool['name']} properties")
    if "session_id" in required:
        required.remove("session_id")
        print(f"  Removed session_id from {tool['name']} required")

# Update LLM
patch_data = json.dumps({"general_tools": llm["general_tools"]}).encode()
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

print("\nUpdated tool parameters:")
for t in result.get("general_tools", []):
    params = t.get("parameters", {})
    print(f"  {t['name']}: required={params.get('required', [])}, props={list(params.get('properties', {}).keys())}")

print("\nDone! session_id removed from tool parameters.")
