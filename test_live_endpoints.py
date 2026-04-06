"""Quick test of live backend AI call endpoints."""
import urllib.request, urllib.error, json

BASE = "https://backend-iota-navy-64.vercel.app"

def post(path, data):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.getcode(), json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:500]

# Test 1: Session creation
print("=== Test 1: Create session ===")
code, session = post("/api/call-order/realtime/session", {"language": "en-IN"})
print(f"Status: {code}")
if isinstance(session, dict):
    print(f"session_id: {session.get('session_id')}")
    provider = session.get("realtime", {}).get("provider", {})
    print(f"provider: {provider.get('name')}")
    print(f"agent_id: {provider.get('agent_id')}")
    print(f"configured: {provider.get('configured')}")
    print(f"missing_fields: {provider.get('missing_fields')}")
    sid = session.get("session_id")
else:
    print(f"Error: {session}")
    sid = None

# Test 2: Retell web call creation
if sid:
    print("\n=== Test 2: Create Retell web call ===")
    code2, webcall = post("/api/call-order/realtime/create-web-call", {
        "session_id": sid,
        "language": "en-IN",
        "metadata": {"sessionId": sid},
    })
    print(f"Status: {code2}")
    if isinstance(webcall, dict):
        print(f"access_token present: {bool(webcall.get('access_token'))}")
        print(f"call_id: {webcall.get('call_id', 'N/A')}")
        for k, v in webcall.items():
            if k != "access_token":
                print(f"  {k}: {v}")
    else:
        print(f"Error: {webcall}")
