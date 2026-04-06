"""List all available Retell voices and find best matches for Indian/Tamil."""
import httpx, os, json
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("RETELL_API_KEY")
BASE_URL = "https://api.retellai.com"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

resp = httpx.get(f"{BASE_URL}/list-voices", headers=HEADERS, timeout=15)
voices = resp.json()
print(f"Total voices: {len(voices)}")

# Filter for Indian/multilingual voices
indian_keywords = ["indian", "tamil", "hindi", "south asian", "multilingual", "desi"]
indian_voices = []
for v in voices:
    s = json.dumps(v).lower()
    if any(kw in s for kw in indian_keywords):
        indian_voices.append(v)

print(f"\n=== Indian/Multilingual voices ({len(indian_voices)}) ===")
for v in indian_voices:
    vn = v.get("voice_name", "?")
    vid = v.get("voice_id", "?")
    prov = v.get("provider", "?")
    gender = v.get("gender", "?")
    accent = v.get("accent", "?")
    lang = v.get("language", "?")
    print(f"  {vid:30s} | {vn:20s} | {prov:12s} | {gender:8s} | accent={accent} | lang={lang}")

# Show all ElevenLabs voices
eleven_voices = [v for v in voices if "eleven" in str(v.get("provider", "")).lower() or v.get("voice_id", "").startswith("11labs")]
print(f"\n=== ElevenLabs voices ({len(eleven_voices)}) ===")
for v in eleven_voices:
    vn = v.get("voice_name", "?")
    vid = v.get("voice_id", "?")
    gender = v.get("gender", "?")
    accent = v.get("accent", "?")
    print(f"  {vid:30s} | {vn:20s} | {gender:8s} | accent={accent}")

# Show all other provider voices
other_voices = [v for v in voices if v not in eleven_voices]
print(f"\n=== Other provider voices ({len(other_voices)}) ===")
for v in other_voices[:30]:
    vn = v.get("voice_name", "?")
    vid = v.get("voice_id", "?")
    prov = v.get("provider", "?")
    gender = v.get("gender", "?")
    accent = v.get("accent", "?")
    print(f"  {vid:30s} | {vn:20s} | {prov:12s} | {gender:8s} | accent={accent}")

# Check current Tamil agent voice
TAMIL_AGENT_ID = os.getenv("AI_CALL_PROVIDER_AGENT_ID_TA")
if TAMIL_AGENT_ID:
    print(f"\n=== Current Tamil Agent ({TAMIL_AGENT_ID}) ===")
    agent_resp = httpx.get(f"{BASE_URL}/get-agent/{TAMIL_AGENT_ID}", headers=HEADERS, timeout=15)
    agent = agent_resp.json()
    print(f"  Voice ID: {agent.get('voice_id')}")
    print(f"  Voice Model: {agent.get('voice_model')}")
    print(f"  Language: {agent.get('language')}")

# Check if custom voice is supported
print("\n=== Custom Voice Support ===")
print("Retell supports custom voices via WebSocket TTS endpoints.")
print("This would allow using Sarvam Bulbul v3 for native Tamil TTS.")
