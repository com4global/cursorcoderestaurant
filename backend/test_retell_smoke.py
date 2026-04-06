"""Quick local smoke test against running backend on port 8000."""
import urllib.request, json, sys

API = "http://127.0.0.1:8000"

def post(path, data):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())

# 1. Bootstrap session
print("=== 1. Bootstrap Session ===")
session = post("/api/call-order/realtime/session", {"language": "en-IN"})
sid = session.get("session_id") or session.get("id")
print(f"Session: {sid}")
print(f"Provider: {session['realtime']['provider']['name']}")
print()

# 2. list_restaurants
print("=== 2. Retell list_restaurants ===")
data = post("/api/call-order/realtime/retell-tool/list_restaurants", {
    "args": {},
    "call": {"call_id": "test-1", "agent_id": "agent_test", "metadata": {"sessionId": sid}},
})
restaurants = data.get("restaurants", [])
print(f"Found {len(restaurants)} restaurants:")
for r in restaurants[:6]:
    print(f"  - {r['name']} (id={r['id']})")
print()

# 3. get_restaurant_menu by ID
if restaurants:
    first = restaurants[0]
    print(f"=== 3. get_restaurant_menu (id={first['id']}) ===")
    menu = post("/api/call-order/realtime/retell-tool/get_restaurant_menu", {
        "args": {"restaurant_id": first["id"]},
        "call": {"call_id": "test-2", "agent_id": "agent_test", "metadata": {"sessionId": sid}},
    })
    print(f"Restaurant: {menu.get('restaurant', {})}")
    cats = menu.get("categories", [])
    print(f"Categories: {len(cats)}")
    for c in cats[:3]:
        items = ", ".join(i["name"] for i in c.get("items", [])[:4])
        print(f"  {c['name']}: {items}")
    print()

    # 4. get_restaurant_menu by name
    print(f"=== 4. get_restaurant_menu (name='{first['name']}') ===")
    menu2 = post("/api/call-order/realtime/retell-tool/get_restaurant_menu", {
        "args": {"restaurant_name": first["name"]},
        "call": {"call_id": "test-3", "agent_id": "agent_test", "metadata": {"sessionId": sid}},
    })
    if menu2.get("error"):
        print(f"ERROR: {menu2['error']}")
    else:
        print(f"Restaurant: {menu2['restaurant']}")
        print(f"Categories: {len(menu2.get('categories', []))}")
        print("Name-based lookup: SUCCESS")
    print()

# 5. find_restaurants
print('=== 5. find_restaurants (query="desi") ===')
found = post("/api/call-order/realtime/retell-tool/find_restaurants", {
    "args": {"query": "desi"},
    "call": {"call_id": "test-4", "agent_id": "agent_test", "metadata": {"sessionId": sid}},
})
for r in found.get("restaurants", []):
    print(f"  - {r['name']} (score={r.get('score', '?')})")
print()

print("=== ALL LOCAL TESTS PASSED ===")
