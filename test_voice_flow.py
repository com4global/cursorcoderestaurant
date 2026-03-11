"""Test the full voice ordering flow end-to-end."""
import json, urllib.request

BASE = "http://localhost:8000"

def api(path, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(f"{BASE}{path}", data=body, headers=headers, method="POST")
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"ERROR {e.code}: {err[:200]}")
        return {}

# 1. Login
print("=== Step 1: Login ===")
res = api("/auth/login", {"email": "test@test.com", "password": "test123"})
token = res.get("access_token", "")
if not token:
    print("Login failed, trying register...")
    res = api("/auth/register", {"email": "test@test.com", "password": "test123", "name": "Test"})
    token = res.get("access_token", "")
print(f"Token: {token[:20]}...")

# 2. Select restaurant via #slug
print("\n=== Step 2: Select #desi-district ===")
res = api("/chat/message", {"text": "#desi-district"}, token)
sid = res.get("session_id", "")
print(f"Session: {sid}")
print(f"Reply: {res.get('reply','')[:100]}")
print(f"Categories: {len(res.get('categories',[]))}")
cats = res.get("categories", [])
if cats:
    print(f"Category names: {[c['name'] for c in cats[:6]]}")

# 3. Send "appetizers" like voice would (WITHOUT the #slug prefix)
print("\n=== Step 3: Voice says 'appetizers' ===")
res = api("/chat/message", {"session_id": sid, "text": "appetizers"}, token)
print(f"Reply: {res.get('reply','')[:200]}")
print(f"Items: {len(res.get('items',[]))}")
print(f"Voice prompt: {res.get('voice_prompt','')[:150]}")
items = res.get("items", [])
if items:
    print(f"Item names: {[i['name'] for i in items[:5]]}")

# 4. Send "snacks"
print("\n=== Step 4: Voice says 'snacks' ===")
res = api("/chat/message", {"session_id": sid, "text": "snacks"}, token)
print(f"Reply: {res.get('reply','')[:200]}")
print(f"Items: {len(res.get('items',[]))}")
items = res.get("items", [])
if items:
    print(f"Item names: {[i['name'] for i in items[:5]]}")

# 5. Test with #slug prefix first (what our code does now)
print("\n=== Step 5: Send #desi-district THEN appetizers (current code flow) ===")
api("/chat/message", {"session_id": sid, "text": "#desi-district"}, token)
res = api("/chat/message", {"session_id": sid, "text": "appetizers"}, token)
print(f"Reply: {res.get('reply','')[:200]}")
print(f"Items: {len(res.get('items',[]))}")
items = res.get("items", [])
if items:
    print(f"Item names: {[i['name'] for i in items[:5]]}")

print("\n=== DONE ===")
