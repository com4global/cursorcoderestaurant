"""Quick local test to verify Retell Custom Function endpoints work."""
from starlette.testclient import TestClient
from app.main import app

client = TestClient(app)

# Step 1: Bootstrap session
print("=== Step 1: Bootstrap Session ===")
res = client.post("/api/call-order/realtime/session", json={"language": "en-IN"})
assert res.status_code == 200, f"Session bootstrap failed: {res.status_code}"
session = res.json()
sid = session.get("session_id") or session.get("id")
print(f"Session ID: {sid}")
print(f"Provider: {session.get('realtime', {}).get('provider', {}).get('name')}")
print()

# Step 2: list_restaurants via Retell Custom Function format
print("=== Step 2: Retell Tool - list_restaurants ===")
res = client.post("/api/call-order/realtime/retell-tool/list_restaurants", json={
    "args": {},
    "call": {"call_id": "test-call-123", "agent_id": "agent_test", "metadata": {"sessionId": sid}},
})
assert res.status_code == 200
data = res.json()
restaurants = data.get("restaurants", [])
print(f"Restaurants found: {len(restaurants)}")
for r in restaurants[:5]:
    print(f"  - {r['name']} (id={r['id']})")
print()

# Step 3: get_restaurant_menu by ID
if restaurants:
    first = restaurants[0]
    print(f"=== Step 3: Retell Tool - get_restaurant_menu (id={first['id']}) ===")
    res = client.post("/api/call-order/realtime/retell-tool/get_restaurant_menu", json={
        "args": {"restaurant_id": first["id"]},
        "call": {"call_id": "test-call-123", "agent_id": "agent_test", "metadata": {"sessionId": sid}},
    })
    assert res.status_code == 200
    menu = res.json()
    print(f"Restaurant: {menu.get('restaurant', {})}")
    cats = menu.get("categories", [])
    print(f"Categories: {len(cats)}")
    for c in cats[:3]:
        items_str = ", ".join(i["name"] for i in c.get("items", [])[:4])
        print(f"  - {c['name']}: {items_str}")
    assert not menu.get("error"), f"Got error: {menu.get('error')}"
    print()

    # Step 4: get_restaurant_menu by name
    print(f"=== Step 4: Retell Tool - get_restaurant_menu (name='{first['name']}') ===")
    res = client.post("/api/call-order/realtime/retell-tool/get_restaurant_menu", json={
        "args": {"restaurant_name": first["name"]},
        "call": {"call_id": "test-call-456", "agent_id": "agent_test", "metadata": {"sessionId": sid}},
    })
    assert res.status_code == 200
    menu2 = res.json()
    print(f"Restaurant: {menu2.get('restaurant', {})}")
    print(f"Categories: {len(menu2.get('categories', []))}")
    if menu2.get("error"):
        print(f"ERROR: {menu2['error']}")
    else:
        print("Name-based lookup: SUCCESS")
    print()

# Step 5: find_restaurants
print('=== Step 5: Retell Tool - find_restaurants (query="pizza") ===')
res = client.post("/api/call-order/realtime/retell-tool/find_restaurants", json={
    "args": {"query": "pizza"},
    "call": {"call_id": "test-call-789", "agent_id": "agent_test", "metadata": {"sessionId": sid}},
})
assert res.status_code == 200
found = res.json()
for r in found.get("restaurants", []):
    print(f"  - {r['name']} (id={r['id']}, score={r.get('score', '?')})")
print()

# Step 6: Missing session_id
print("=== Step 6: Missing session_id (should return error gracefully) ===")
res = client.post("/api/call-order/realtime/retell-tool/list_restaurants", json={
    "args": {},
    "call": {"call_id": "test-no-session", "agent_id": "agent_test"},
})
assert res.status_code == 200
err_data = res.json()
assert "error" in err_data or "Missing" in str(err_data)
print(f"Response: {err_data}")
print()

print("=== ALL RETELL TOOL TESTS PASSED ===")
