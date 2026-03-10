"""
Sarvam AI service wrapper for STT (Saaras v3) and TTS (Bulbul v3).
Uses the raw HTTP API for maximum control and minimal dependencies.
"""
from __future__ import annotations

import base64
import io
import json
import os
import urllib.request
import urllib.error

from dotenv import load_dotenv
load_dotenv()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_BASE = "https://api.sarvam.ai"


def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> dict:
    """
    Send audio to Sarvam Saaras v3 STT.
    Returns {"transcript": str, "language": str}
    """
    import uuid
    boundary = uuid.uuid4().hex

    # Detect content type from filename
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "webm"
    mime_map = {
        "webm": "audio/webm", "wav": "audio/wav", "mp3": "audio/mpeg",
        "ogg": "audio/ogg", "m4a": "audio/mp4", "aac": "audio/aac",
    }
    content_type = mime_map.get(ext, "audio/webm")

    # Build multipart form data
    body = b""
    # File field
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
    body += f"Content-Type: {content_type}\r\n\r\n".encode()
    body += audio_bytes
    body += b"\r\n"
    # Model field
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="model"\r\n\r\n'
    body += b"saaras:v3\r\n"
    # Mode field
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="mode"\r\n\r\n'
    body += b"transcribe\r\n"
    # End boundary
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{SARVAM_BASE}/speech-to-text",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "api-subscription-key": SARVAM_API_KEY,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return {
                "transcript": data.get("transcript", ""),
                "language": data.get("language_code", "en-IN"),
            }
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        raise RuntimeError(f"Sarvam STT error ({e.code}): {error_body}")
    except Exception as e:
        raise RuntimeError(f"Sarvam STT error: {str(e)}")


def generate_speech(
    text: str,
    language: str = "en-IN",
    speaker: str = "kavya",
) -> dict:
    """
    Send text to Sarvam Bulbul v3 TTS.
    Returns {"audio_base64": str, "format": "wav"}
    """
    payload = {
        "text": text,
        "target_language_code": language,
        "model": "bulbul:v3",
        "speaker": speaker,
        "audio_format": "wav",
        "sample_rate": 22050,
    }

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{SARVAM_BASE}/text-to-speech",
        data=body,
        headers={
            "Content-Type": "application/json",
            "api-subscription-key": SARVAM_API_KEY,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            # Sarvam returns {"audios": ["base64..."]}
            audios = data.get("audios", [])
            audio_b64 = audios[0] if audios else ""
            return {
                "audio_base64": audio_b64,
                "format": "wav",
            }
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        raise RuntimeError(f"Sarvam TTS error ({e.code}): {error_body}")
    except Exception as e:
        raise RuntimeError(f"Sarvam TTS error: {str(e)}")


def chat_completion(
    user_message: str,
    system_prompt: str = "",
    context: str = "",
) -> str:
    """
    Send a message to Sarvam chat completion API (sarvam-m model).
    Returns the assistant's reply text.
    """
    messages = []
    # Sarvam requires exactly one system message at the start
    combined_system = system_prompt
    if context:
        combined_system += f"\n\nCurrent context: {context}"
    if combined_system:
        messages.append({"role": "system", "content": combined_system})
    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": "sarvam-m",
        "messages": messages,
        "max_tokens": 200,
        "temperature": 0.7,
    }

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{SARVAM_BASE}/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "api-subscription-key": SARVAM_API_KEY,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            choices = data.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                # Strip <think> and </think> tags (Sarvam prefixes responses with <think>)
                import re
                content = re.sub(r"</?think>", "", content).strip()
                return content
            return ""
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        raise RuntimeError(f"Sarvam chat error ({e.code}): {error_body}")
    except Exception as e:
        raise RuntimeError(f"Sarvam chat error: {str(e)}")
