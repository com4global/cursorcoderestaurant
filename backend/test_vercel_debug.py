"""Debug menu lookup on Vercel."""
import urllib.request
import json

BASE = "https://backend-iota-navy-64.vercel.app"

def post(path, body):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=20)
    return json.loads(resp.read())

# 1. Create session
session = post("/api/call-order/realtime/session", {"restaurant_id": 1, "language": "en"})
sid = session.get("session_id") or session.get("sessionId")
print(f"Session: {sid}")

# 2. List restaurants to get IDs
result = post("/api/call-order/realtime/retell-tool/list_restaurants", {
    "args": {},
    "call": {"call_id": "t1", "agent_id": "t", "metadata": {"sessionId": sid}}
})
for r in result.get("restaurants", []):
    print(f"  id={r.get('id')} name={r.get('name')}")

# 3. Get menu by name - full response
menu = post("/api/call-order/realtime/retell-tool/get_restaurant_menu", {
    "args": {"restaurant_name": "Anjappar"},
    "call": {"call_id": "t2", "agent_id": "t", "metadata": {"sessionId": sid}}
})
print(f"\nMenu response (by name 'Anjappar'):")
print(json.dumps(menu, indent=2)[:1000])

# 4. Get menu by ID (use Anjappar's ID)
anjappar_id = None
for r in result.get("restaurants", []):
    if "Anjappar" in r.get("name", "") or "anjappar" in r.get("name", "").lower():
        anjappar_id = r.get("id")
        break

if anjappar_id:
    print(f"\nTrying by ID: {anjappar_id}")
    menu2 = post("/api/call-order/realtime/retell-tool/get_restaurant_menu", {
        "args": {"restaurant_id": str(anjappar_id)},
        "call": {"call_id": "t3", "agent_id": "t", "metadata": {"sessionId": sid}}
    })
    print(f"Menu response (by id {anjappar_id}):")
    print(json.dumps(menu2, indent=2)[:1000])
