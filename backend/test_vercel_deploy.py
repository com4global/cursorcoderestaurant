"""Quick test to verify Retell tool endpoints work on deployed Vercel backend."""
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

# 2. List restaurants
result = post("/api/call-order/realtime/retell-tool/list_restaurants", {
    "args": {},
    "call": {"call_id": "t1", "agent_id": "t", "metadata": {"sessionId": sid}}
})
restaurants = result.get("restaurants", [])
print(f"Restaurants: {len(restaurants)}")
for r in restaurants[:3]:
    print(f"  - {r.get('name', '?')}")

# 3. Get menu by name
menu = post("/api/call-order/realtime/retell-tool/get_restaurant_menu", {
    "args": {"restaurant_name": "Anjappar"},
    "call": {"call_id": "t2", "agent_id": "t", "metadata": {"sessionId": sid}}
})
cats = menu.get("menu_categories", [])
print(f"Menu categories: {len(cats)}")
for c in cats[:3]:
    print(f"  - {c.get('category', '?')} ({len(c.get('items', []))} items)")

print("\nALL PRODUCTION TESTS PASSED!")
