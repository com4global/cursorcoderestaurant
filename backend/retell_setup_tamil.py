"""
Script to:
1. Fetch the current English Retell agent config
2. Create a new Tamil agent with multilingual voice
3. Update .env with the new Tamil agent ID
"""
import httpx
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("RETELL_API_KEY")
ENGLISH_AGENT_ID = os.getenv("AI_CALL_PROVIDER_AGENT_ID")
BASE_URL = "https://api.retellai.com"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}


def get_agent(agent_id):
    resp = httpx.get(f"{BASE_URL}/get-agent/{agent_id}", headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def list_voices():
    """List available voices to find multilingual ones."""
    resp = httpx.get(f"{BASE_URL}/list-voices", headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def create_agent(payload):
    resp = httpx.post(f"{BASE_URL}/create-agent", json=payload, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def update_agent(agent_id, payload):
    resp = httpx.patch(f"{BASE_URL}/update-agent/{agent_id}", json=payload, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def main():
    if not API_KEY:
        print("ERROR: RETELL_API_KEY not set")
        sys.exit(1)
    if not ENGLISH_AGENT_ID:
        print("ERROR: AI_CALL_PROVIDER_AGENT_ID not set")
        sys.exit(1)

    # Step 1: Fetch current English agent
    print(f"Fetching English agent: {ENGLISH_AGENT_ID}")
    eng_agent = get_agent(ENGLISH_AGENT_ID)
    print(f"  Name: {eng_agent.get('agent_name')}")
    print(f"  Voice ID: {eng_agent.get('voice_id')}")
    print(f"  Voice Model: {eng_agent.get('voice_model')}")
    print(f"  Language: {eng_agent.get('language')}")
    print(f"  Response Engine: {json.dumps(eng_agent.get('response_engine'), indent=2) if eng_agent.get('response_engine') else 'None'}")
    print()

    # Print the general prompt
    gp = eng_agent.get("general_prompt", "")
    print(f"  General Prompt (first 300 chars): {gp[:300]}")
    print()

    # Step 2: Check if English agent already has {{language_instruction}}
    if "{{language_instruction}}" not in (gp or ""):
        print("  NOTE: English agent does NOT have {{language_instruction}} placeholder.")
        print("  Updating English agent to add it...")
        updated_prompt = "{{language_instruction}}\n\n" + gp if gp else "{{language_instruction}}"
        update_agent(ENGLISH_AGENT_ID, {"general_prompt": updated_prompt})
        print("  Done - English agent prompt updated with {{language_instruction}}")
        print()

    # Step 3: List voices to find multilingual options
    print("Listing available voices...")
    voices = list_voices()
    # Find multilingual voices
    multilingual = []
    for v in voices:
        vname = v.get("voice_name", "")
        vid = v.get("voice_id", "")
        provider = v.get("provider", "")
        accent = v.get("accent", "")
        gender = v.get("gender", "")
        lang = v.get("language", "")
        # Look for multilingual, Indian, or Tamil voices
        is_multi = any(
            kw in str(v).lower()
            for kw in ["multilingual", "multi", "indian", "tamil", "hindi"]
        )
        if is_multi:
            multilingual.append(v)

    if multilingual:
        print(f"  Found {len(multilingual)} multilingual/Indian voices:")
        for v in multilingual[:10]:
            print(f"    - {v.get('voice_name')} ({v.get('voice_id')}) "
                  f"[{v.get('provider')}, {v.get('gender')}, {v.get('accent')}]")
    else:
        print("  No specifically multilingual voices found. Listing all voices:")
        for v in voices[:15]:
            print(f"    - {v.get('voice_name')} ({v.get('voice_id')}) "
                  f"[{v.get('provider')}, {v.get('gender')}, {v.get('accent')}]")
    print()

    # Step 4: Create Tamil agent
    # Clone from English agent, change voice to multilingual
    # Use Eleven Labs multilingual voice if available
    eleven_multi = [
        v for v in voices
        if "eleven" in str(v.get("provider", "")).lower()
        and any(kw in str(v).lower() for kw in ["multilingual", "multi"])
    ]

    # Fallback: just pick any indian/multilingual voice or first Eleven Labs voice
    eleven_voices = [v for v in voices if "eleven" in str(v.get("provider", "")).lower()]

    chosen_voice = None
    if eleven_multi:
        chosen_voice = eleven_multi[0]
    elif eleven_voices:
        chosen_voice = eleven_voices[0]
    elif voices:
        chosen_voice = voices[0]

    if not chosen_voice:
        print("ERROR: No voices available")
        sys.exit(1)

    print(f"Selected voice for Tamil agent: {chosen_voice.get('voice_name')} ({chosen_voice.get('voice_id')})")
    print()

    # Build Tamil agent payload
    tamil_prompt = (
        "{{language_instruction}}\n\n" + gp if gp else "{{language_instruction}}"
    )

    tamil_payload = {
        "agent_name": "RestaurantAI Tamil (Tanglish)",
        "voice_id": chosen_voice.get("voice_id"),
        "language": "multi",  # multilingual
        "general_prompt": tamil_prompt,
    }

    # Copy over response engine config if it exists
    if eng_agent.get("response_engine"):
        tamil_payload["response_engine"] = eng_agent["response_engine"]

    # Copy over webhook/tool config
    for key in ["webhook_url", "agent_type", "voice_model", "voice_speed",
                 "voice_temperature", "responsiveness", "interruption_sensitivity",
                 "enable_backchannel", "backchannel_frequency",
                 "ambient_sound", "ambient_sound_volume",
                 "end_call_after_silence_ms", "max_call_duration_ms",
                 "normalize_for_speech", "opt_out_sensitive_data_storage"]:
        if eng_agent.get(key) is not None:
            tamil_payload[key] = eng_agent[key]

    # Copy custom tools if they exist
    if eng_agent.get("functions"):
        tamil_payload["functions"] = eng_agent["functions"]

    print("Creating Tamil agent...")
    print(f"  Payload keys: {list(tamil_payload.keys())}")

    tamil_agent = create_agent(tamil_payload)
    tamil_agent_id = tamil_agent.get("agent_id")
    print(f"  Created Tamil agent: {tamil_agent_id}")
    print(f"  Name: {tamil_agent.get('agent_name')}")
    print(f"  Voice: {tamil_agent.get('voice_id')}")
    print(f"  Language: {tamil_agent.get('language')}")
    print()

    # Step 5: Update .env file
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            env_content = f.read()

        # Check if AI_CALL_PROVIDER_AGENT_ID_TA already exists
        if "AI_CALL_PROVIDER_AGENT_ID_TA=" in env_content:
            # Replace existing line
            lines = env_content.split("\n")
            for i, line in enumerate(lines):
                if line.startswith("AI_CALL_PROVIDER_AGENT_ID_TA="):
                    lines[i] = f"AI_CALL_PROVIDER_AGENT_ID_TA={tamil_agent_id}"
            env_content = "\n".join(lines)
        else:
            # Add after AI_CALL_PROVIDER_AGENT_ID_EN line
            lines = env_content.split("\n")
            for i, line in enumerate(lines):
                if line.startswith("AI_CALL_PROVIDER_AGENT_ID_EN="):
                    lines.insert(i + 1, f"AI_CALL_PROVIDER_AGENT_ID_TA={tamil_agent_id}")
                    break
            else:
                lines.append(f"AI_CALL_PROVIDER_AGENT_ID_TA={tamil_agent_id}")
            env_content = "\n".join(lines)

        with open(env_path, "w") as f:
            f.write(env_content)
        print(f"Updated .env: AI_CALL_PROVIDER_AGENT_ID_TA={tamil_agent_id}")
    else:
        print(f"WARNING: .env not found at {env_path}")
        print(f"Manually add: AI_CALL_PROVIDER_AGENT_ID_TA={tamil_agent_id}")

    print()
    print("=== DONE ===")
    print(f"English Agent: {ENGLISH_AGENT_ID}")
    print(f"Tamil Agent:   {tamil_agent_id}")
    print("Restart the backend to pick up the new agent ID.")


if __name__ == "__main__":
    main()
