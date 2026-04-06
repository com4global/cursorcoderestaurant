"""Test Tamil multi-turn call-order flow."""
import urllib.request
import json
import re
import sys

BASE = "http://127.0.0.1:8000"


def post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode())


session = post("/api/call-order/session", {"restaurant_id": None, "language": "ta-IN"})
sid = session["session_id"]
print(f"Session: {sid[:12]}...")

ALLOWED_ENG = {
    "aroma", "anjappar", "pizza", "debug", "desi", "district",
    "dominos", "biryani", "chicken",
}

turns = [
    ("aroma select", "\u0b85\u0bb0\u0bcb\u0bae\u0bbe."),
    ("chicken biryani", "\u0b9a\u0bbf\u0b95\u0bcd\u0b95\u0ba9\u0bcd \u0baa\u0bbf\u0bb0\u0bbf\u0baf\u0bbe\u0ba3\u0bbf."),
    ("how much", "\u0b8e\u0bb5\u0bcd\u0bb5\u0bb3\u0bb5\u0bc1?"),
]

all_ok = True
for label, t in turns:
    resp = post("/api/call-order/turn", {"session_id": sid, "transcript": t})
    reply = resp.get("assistant_reply", "")
    tamil_count = len(re.findall(r"[\u0B80-\u0BFF]", reply))
    eng_words = re.findall(r"[a-zA-Z]{4,}", reply)
    bad_eng = [w for w in eng_words if w.lower() not in ALLOWED_ENG]
    ok = tamil_count > 3 and len(bad_eng) == 0
    print(f"\n[{label}] transcript: {t}")
    print(f"  reply: {reply[:250]}")
    print(f"  Tamil chars: {tamil_count}, Bad English: {bad_eng}")
    print(f"  => {'OK' if ok else 'FAIL'}")
    if not ok:
        all_ok = False

print(f"\n{'ALL PASSED' if all_ok else 'SOME FAILED'}")
sys.exit(0 if all_ok else 1)
