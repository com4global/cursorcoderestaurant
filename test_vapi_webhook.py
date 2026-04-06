import requests, json

# First create a session
r = requests.post("http://localhost:8000/api/call-order/realtime/session", json={"language": "en-IN"})
session = r.json()
sid = session.get("session_id") or session.get("id")
print(f"Session: {sid}")

# Test the Vapi webhook with list_restaurants
webhook_payload = {
    "message": {
        "type": "tool-calls",
        "toolCallList": [
            {
                "id": "call_test123",
                "name": "list_restaurants",
                "arguments": {"limit": 5}
            }
        ],
        "assistant": {
            "metadata": {
                "sessionId": sid
            }
        }
    }
}

r2 = requests.post("http://localhost:8000/api/call-order/realtime/vapi-webhook", json=webhook_payload)
print(f"\nWebhook status: {r2.status_code}")
result = r2.json()
print(f"Webhook response: {json.dumps(result, indent=2)}")

# Parse the result string
if result.get("results"):
    first = result["results"][0]
    parsed = json.loads(first.get("result", "{}"))
    print(f"\nParsed result: {len(parsed.get('restaurants', []))} restaurants")
    for r in parsed.get("restaurants", []):
        print(f"  - {r['name']} (id={r['id']})")

# Test find_restaurants
webhook_payload2 = {
    "message": {
        "type": "tool-calls",
        "toolCallList": [
            {
                "id": "call_test456",
                "name": "find_restaurants",
                "arguments": {"query": "Aroma"}
            }
        ],
        "assistant": {
            "metadata": {
                "sessionId": sid
            }
        }
    }
}

r3 = requests.post("http://localhost:8000/api/call-order/realtime/vapi-webhook", json=webhook_payload2)
print(f"\nFind restaurants status: {r3.status_code}")
result3 = r3.json()
if result3.get("results"):
    parsed3 = json.loads(result3["results"][0].get("result", "{}"))
    print(f"Found: {parsed3.get('restaurants', [])}")

# Test get_restaurant_menu
if parsed.get("restaurants"):
    rid = parsed["restaurants"][0]["id"]
    webhook_payload3 = {
        "message": {
            "type": "tool-calls",
            "toolCallList": [
                {
                    "id": "call_test789",
                    "name": "get_restaurant_menu",
                    "arguments": {"restaurant_id": rid}
                }
            ],
            "assistant": {
                "metadata": {
                    "sessionId": sid
                }
            }
        }
    }
    r4 = requests.post("http://localhost:8000/api/call-order/realtime/vapi-webhook", json=webhook_payload3)
    print(f"\nMenu status: {r4.status_code}")
    result4 = r4.json()
    if result4.get("results"):
        parsed4 = json.loads(result4["results"][0].get("result", "{}"))
        print(f"Restaurant: {parsed4.get('restaurant', {}).get('name')}")
        print(f"Categories: {len(parsed4.get('categories', []))}")
        for c in parsed4.get("categories", [])[:3]:
            print(f"  - {c['name']}: {len(c.get('items', []))} items")
