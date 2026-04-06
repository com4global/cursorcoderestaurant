"""Quick test: verify Tamil call-order turns reply in Tamil, not English."""
import urllib.request
import json
import re
import sys

BASE = "http://127.0.0.1:8000"

def post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

# 1. Create Tamil session
session = post("/api/call-order/session", {"restaurant_id": None, "language": "ta-IN"})
sid = session["session_id"]
print(f"Session: {sid[:12]}...")
print(f"Greeting: {session.get('last_assistant_reply', session.get('reply', ''))[:80]}")

# 2. Send Tamil transcript
turns = [
    "அரோமா கடையில இருந்து வேணும்",
    "பிரியாணி வேணும்",
]

ok = True
for t in turns:
    resp = post("/api/call-order/turn", {"session_id": sid, "transcript": t})
    reply = resp.get("assistant_reply", resp.get("reply", ""))
    tamil_chars = len(re.findall(r"[\u0B80-\u0BFF]", reply))
    eng_words = re.findall(r"[a-zA-Z]{4,}", reply)
    # Restaurant names in English are OK
    allowed_eng = {"aroma", "Aroma", "Anjappar", "Pizza", "Debug", "Desi", "District", "dominos", "Dominos"}
    bad_eng = [w for w in eng_words if w not in allowed_eng]

    status = "OK" if tamil_chars > 5 and len(bad_eng) == 0 else "FAIL"
    print(f"\nTranscript: {t}")
    print(f"Reply: {reply[:300]}")
    print(f"Tamil chars: {tamil_chars}, Bad English words: {bad_eng}")
    print(f"Status: {status}")
    if status == "FAIL":
        ok = False

sys.exit(0 if ok else 1)
