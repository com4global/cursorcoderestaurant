"""Optimize Retell agent settings for better conversation quality."""
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("RETELL_API_KEY")
TAMIL_ID = os.getenv("AI_CALL_PROVIDER_AGENT_ID_TA")
ENG_ID = os.getenv("AI_CALL_PROVIDER_AGENT_ID_EN")
BASE = "https://api.retellai.com"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

FOOD_KEYWORDS = [
    "biryani", "dum biryani", "chicken dum biryani", "chicken 65 biryani",
    "egg biryani", "mutton biryani",
    "dosa", "idli", "sambar", "naan", "paneer", "chicken", "mutton",
    "parotta", "filter coffee", "masala", "tandoori", "rasam",
    "curd rice", "thali", "kurma", "korma", "chapathi",
    "order", "add", "cart", "menu", "checkout",
    "Anjappar", "Aroma", "Desi District",
]

# Tamil agent: use language="en" so STT transcribes in English.
# The LLM prompt + dynamic variable handles Tanglish output.
# "multi" mode misdetects Tamil as Hindi, garbling food names.
tamil_settings = {
    "language": "en-US",
    "responsiveness": 0.7,
    "interruption_sensitivity": 1.0,
    "enable_backchannel": False,
    "backchannel_frequency": 0.3,
    "voice_speed": 0.95,
    "voice_temperature": 0.5,
    "normalize_for_speech": True,
    "end_call_after_silence_ms": 30000,
    "boosted_keywords": FOOD_KEYWORDS,
}

# English agent
eng_settings = {
    "language": "en-US",
    "responsiveness": 0.7,
    "interruption_sensitivity": 1.0,
    "enable_backchannel": False,
    "backchannel_frequency": 0.3,
    "voice_id": "11labs-Adrian",
    "voice_speed": 1.0,
    "voice_temperature": 0.4,
    "normalize_for_speech": True,
    "end_call_after_silence_ms": 30000,
    "boosted_keywords": FOOD_KEYWORDS,
}

for label, aid, settings in [("Tamil", TAMIL_ID, tamil_settings), ("English", ENG_ID, eng_settings)]:
    print(f"Updating {label} agent ({aid})...")
    r = httpx.patch(
        f"{BASE}/update-agent/{aid}",
        json=settings,
        headers=HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    d = r.json()
    print(f"  language: {d.get('language')}")
    print(f"  responsiveness: {d.get('responsiveness')}")
    print(f"  interruption_sensitivity: {d.get('interruption_sensitivity')}")
    print(f"  enable_backchannel: {d.get('enable_backchannel')}")
    print(f"  voice_speed: {d.get('voice_speed')}")
    print(f"  boosted_keywords: {len(d.get('boosted_keywords', []))} words")
    print(f"  Done!")
    print()

print("=== Both agents optimized ===")
