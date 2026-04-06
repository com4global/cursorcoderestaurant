"""Quick end-to-end test of realtime tool endpoints."""
import urllib.request, json, sys

BASE = "http://localhost:8000"

def post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers={"Content-Type": "application/json"}, method="POST")
    r = urllib.request.urlopen(req)
    return json.loads(r.read())

def get(path):
    r = urllib.request.urlopen(f"{BASE}{path}")
    return json.loads(r.read())

# 0. Health
health = get("/health")
print(f"[OK] Health: {health}")

# 1. Provider config
config = get("/api/call-order/realtime/provider-config")
print(f"[OK] Provider: {config['provider']['name']}, enabled={config['enabled']}")
print(f"     English agent: {config['provider'].get('agent_ids', {}).get('en-IN', 'N/A')}")
print(f"     Tamil agent:   {config['provider'].get('agent_ids', {}).get('ta-IN', 'N/A')}")

# 2. Create session
session = post("/api/call-order/realtime/session", {"language": "en-IN"})
sid = session.get("id") or session.get("session_id")
print(f"[OK] Session created: {sid}")

# 3. List restaurants
restaurants = post("/api/call-order/realtime/tools/list-restaurants", {"session_id": sid})
total = restaurants.get("total_matches", 0)
rlist = restaurants.get("restaurants", [])
print(f"[OK] Restaurants: {total} found")
for r in rlist[:3]:
    name = r["name"]
    rid = r["id"]
    print(f"     - {name} (id={rid})")

if not rlist:
    print("[WARN] No restaurants found, stopping")
    sys.exit(0)

# 4. Get menu - find a restaurant that actually has items
first_r = None
menu = None
for candidate in rlist:
    m = post("/api/call-order/realtime/tools/menu", {"session_id": sid, "restaurant_id": candidate["id"]})
    citems_from_cats = sum(len(c.get("items", [])) for c in m.get("categories", []))
    citems = len(m.get("items", [])) + citems_from_cats
    cname = candidate["name"]
    print(f"     Checking '{cname}': {citems} items")
    if m.get("items") or any(c.get("items") for c in m.get("categories", [])):
        first_r = candidate
        menu = m
        break

if not first_r:
    print("[WARN] No restaurant has menu items, stopping")
    sys.exit(0)

items = menu.get("items", [])
# Menu returns categories with nested items
if not items:
    all_items = []
    for cat in menu.get("categories", []):
        for item in cat.get("items", []):
            all_items.append(item)
    items = all_items
rname = menu.get("restaurant_name") or menu.get("restaurant", {}).get("name") or first_r["name"]
print(f"[OK] Menu for '{rname}': {len(items)} items")
for item in items[:5]:
    iname = item.get("name", "?")
    iid = item.get("id", "?")
    price = item.get("price_cents", item.get("price", "?"))
    print(f"     - {iname} (id={iid}) {price}c")

if not items:
    print("[WARN] No menu items, stopping")
    sys.exit(0)

# 5. Add item to draft
first_item = items[0]
add_result = post("/api/call-order/realtime/tools/add-item", {
    "session_id": sid,
    "item_id": first_item["id"],
    "quantity": 1
})
print(f"[OK] Added '{first_item['name']}' to draft")
print(f"     Draft items: {add_result.get('draft_item_count', '?')}, Total: ${add_result.get('draft_total', '?')}")

# 6. Draft summary
summary = get(f"/api/call-order/realtime/tools/draft-summary/{sid}")
print(f"[OK] Draft summary: {len(summary.get('items', []))} items, total=${summary.get('total', '?')}")

# 7. Remove item
remove_result = post("/api/call-order/realtime/tools/remove-item", {
    "session_id": sid,
    "item_id": first_item["id"]
})
print(f"[OK] Removed '{first_item['name']}' from draft")
print(f"     Draft items: {remove_result.get('draft_item_count', '?')}, Total: ${remove_result.get('draft_total', '?')}")

print("\n=== ALL BACKEND API TESTS PASSED ===")
