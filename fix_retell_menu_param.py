"""Add restaurant_name parameter to get_restaurant_menu tool definition."""
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

for tool in llm.get("general_tools", []):
    if tool["name"] == "get_restaurant_menu":
        props = tool["parameters"]["properties"]
        if "restaurant_name" not in props:
            props["restaurant_name"] = {
                "type": "string",
                "description": "Restaurant name (alternative to restaurant_id)"
            }
            print("Added restaurant_name to get_restaurant_menu")
        # Make restaurant_id not strictly required since name works too
        tool["parameters"]["required"] = []
        print(f"Updated required: {tool['parameters']['required']}")
    
    if tool["name"] == "add_draft_item":
        props = tool["parameters"]["properties"]
        if "item_name" not in props:
            props["item_name"] = {
                "type": "string",
                "description": "Item name for reference"
            }
        if "restaurant_id" not in props:
            props["restaurant_id"] = {
                "type": "number",
                "description": "Restaurant ID the item belongs to"
            }

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

print("\nFinal tool definitions:")
for t in result.get("general_tools", []):
    params = t.get("parameters", {})
    print(f"  {t['name']}:")
    print(f"    url: {t.get('url')}")
    print(f"    required: {params.get('required', [])}")
    print(f"    props: {list(params.get('properties', {}).keys())}")
