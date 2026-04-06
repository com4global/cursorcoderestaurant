"""
Voice endpoints for Sarvam AI STT + TTS + Conversation.
POST /api/voice/stt       — receive audio blob, return transcript
POST /api/voice/tts       — receive text, return base64 audio
POST /api/voice/chat      — receive text, return AI reply
POST /api/voice/converse  — full pipeline: audio → STT → chat engine → TTS → audio reply
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import sarvam_service, chat, crud, models
from .chat import _pipeline_log, get_voice_pipeline_log
from .auth import get_current_user
from .db import get_db

router = APIRouter(prefix="/api/voice", tags=["voice"])

# ---------- STT Trace Log (in-memory, last 50 calls) ----------
import time as _time
from collections import deque
_stt_log = deque(maxlen=50)


@router.get("/stt-log")
async def get_stt_log():
    """Retrieve recent STT call logs for debugging."""
    return {"logs": list(_stt_log), "count": len(_stt_log)}


@router.get("/pipeline-log")
async def get_pipeline_log():
    """Retrieve recent voice pipeline log entries for real-time debugging."""
    return {"logs": get_voice_pipeline_log(), "count": len(get_voice_pipeline_log())}


# ---------- STT ----------

def _normalize_stt_lang(lang: str) -> str:
    """Only en-IN or ta-IN so STT matches user selection (default English)."""
    if lang and str(lang).strip().lower().startswith("ta"):
        return "ta-IN"
    return "en-IN"


@router.post("/stt")
async def speech_to_text(file: UploadFile = File(...), language: str = Form("en-IN")):
    """Transcribe uploaded audio using Sarvam Saaras v3."""
    t0 = _time.time()
    audio_bytes = await file.read()
    filename = file.filename or "audio.webm"
    content_type = file.content_type or "unknown"
    audio_kb = len(audio_bytes) / 1024
    lang = _normalize_stt_lang(language)

    log_entry = {
        "ts": _time.strftime("%Y-%m-%d %H:%M:%S"),
        "filename": filename,
        "content_type": content_type,
        "audio_kb": round(audio_kb, 1),
        "language_requested": lang,
        "transcript": None,
        "detected_lang": None,
        "duration_ms": None,
        "error": None,
    }

    print(f"[STT] ← {audio_kb:.1f}KB | file={filename} | lang={lang}")
    _pipeline_log('STT', f'STT request: {audio_kb:.1f}KB, lang={lang}', {'filename': filename, 'content_type': content_type, 'audio_kb': round(audio_kb, 1), 'lang': lang})

    if len(audio_bytes) == 0:
        log_entry["error"] = "Empty audio"
        _stt_log.append(log_entry)
        raise HTTPException(400, "Empty audio file")
    if len(audio_bytes) > 10 * 1024 * 1024:
        log_entry["error"] = "Too large"
        _stt_log.append(log_entry)
        raise HTTPException(400, "Audio file too large (max 10MB)")

    try:
        result = sarvam_service.transcribe_audio(
            audio_bytes,
            filename=filename,
            language_code=lang,
        )
        elapsed = (_time.time() - t0) * 1000
        transcript = result.get("transcript", "")
        detected = result.get("language", "")

        log_entry["transcript"] = transcript
        log_entry["detected_lang"] = detected
        log_entry["duration_ms"] = round(elapsed)

        print(f"[STT] → \"{transcript}\" | detected={detected} | ⏱{elapsed:.0f}ms")
        _pipeline_log('STT', f'STT result: "{transcript}"', {'transcript': transcript, 'detected_lang': detected, 'duration_ms': round(elapsed), 'audio_kb': round(audio_kb, 1)})
        _stt_log.append(log_entry)
        return result
    except RuntimeError as e:
        elapsed = (_time.time() - t0) * 1000
        log_entry["error"] = str(e)[:200]
        log_entry["duration_ms"] = round(elapsed)
        print(f"[STT] ✗ {str(e)[:100]} | ⏱{elapsed:.0f}ms")
        _pipeline_log('ERROR', f'STT failed: {str(e)[:100]}', {'duration_ms': round(elapsed)})
        _stt_log.append(log_entry)
        raise HTTPException(502, str(e))


# ---------- TTS ----------

class TTSRequest(BaseModel):
    text: str
    language: str = "en-IN"
    speaker: str = "kavya"


def _normalize_tts_lang(lang: str) -> str:
    """Only en-IN or ta-IN so Sarvam output matches user selection (default English)."""
    if lang and str(lang).strip().lower().startswith("ta"):
        return "ta-IN"
    return "en-IN"


@router.post("/tts")
async def text_to_speech(req: TTSRequest):
    """Convert text to speech using Sarvam Bulbul v3."""
    import time
    t0 = time.time()
    if not req.text.strip():
        raise HTTPException(400, "Text cannot be empty")
    if len(req.text) > 2500:
        # Sarvam v3 limit is 2500 chars
        req.text = req.text[:2500]

    lang = _normalize_tts_lang(req.language)
    try:
        result = sarvam_service.generate_speech(
            text=req.text,
            language=lang,
            speaker=req.speaker,
        )
        elapsed = (time.time() - t0) * 1000
        tts_text_snippet = req.text[:60] + ('...' if len(req.text) > 60 else '')
        print(f"[TTS] \u23f1 {elapsed:.0f}ms | lang={lang} | text=\"{tts_text_snippet}\"")
        _pipeline_log('TTS', f'TTS generated: {elapsed:.0f}ms', {'text': req.text[:80], 'lang': lang, 'speaker': req.speaker, 'duration_ms': round(elapsed)})
        return result
    except RuntimeError as e:
        raise HTTPException(502, str(e))


# ---------- Chat Agent ----------

class ChatRequest(BaseModel):
    message: str
    context: str = ""


_VOICE_GROUP_PHRASES = (
    "group order", "group ordering", "start a group order", "order as a group",
    "group lunch", "group dinner", "office lunch", "company lunch",
    "order for the team", "order for the office",
)
_VOICE_GROUP_PATTERN = re.compile(
    r"(?:find|get|order|want|need)\s+(?:food|meals?|lunch|dinner)\s+for\s+(\d+)\s+people",
    re.I,
)


def _voice_group_order_response(message: str) -> dict | None:
    lower = message.lower().strip()
    if any(phrase in lower for phrase in _VOICE_GROUP_PHRASES) or _VOICE_GROUP_PATTERN.search(lower):
        return {
            "reply": "Open the Group Order tab to start a group order. Share the link with friends, add their preferences, and get AI recommendations for the whole group!",
            "open_group_tab": True,
        }
    return None


@router.post("/chat")
async def voice_chat(req: ChatRequest):
    """Get intelligent response from Sarvam AI agent."""
    if not req.message.strip():
        raise HTTPException(400, "Message cannot be empty")

    group_intent = _voice_group_order_response(req.message)
    if group_intent is not None:
        return group_intent

    system_prompt = (
        "You are a friendly restaurant ordering assistant. "
        "Help users browse restaurants, choose categories, select menu items, and place orders. "
        "Keep responses short (under 50 words), natural, and conversational. "
        "If the user mentions a food item or category, help them find it. "
        "Respond in the same language the user speaks."
    )

    try:
        reply = sarvam_service.chat_completion(
            user_message=req.message,
            system_prompt=system_prompt,
            context=req.context,
        )
        return {"reply": reply}
    except RuntimeError as e:
        raise HTTPException(502, str(e))


# ---------- Full Conversation Pipeline ----------

@router.post("/converse")
async def voice_converse(
    file: UploadFile = File(...),
    session_id: int = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Full voice conversation pipeline:
    1. STT: transcribe audio → text
    2. Chat: process_message (existing chat engine with restaurant/menu/cart logic)
    3. TTS: convert voice_prompt → audio (Indian accent, Sarvam Bulbul v3)
    Returns { transcript, reply, voice_prompt, audio_base64, session_id, ... }
    """
    # --- Step 1: STT ---
    audio_bytes = await file.read()
    if len(audio_bytes) == 0:
        raise HTTPException(400, "Empty audio file")
    if len(audio_bytes) > 10 * 1024 * 1024:
        raise HTTPException(400, "Audio file too large (max 10MB)")

    try:
        stt_result = sarvam_service.transcribe_audio(
            audio_bytes,
            filename=file.filename or "audio.webm",
        )
    except RuntimeError as e:
        raise HTTPException(502, f"STT error: {str(e)}")

    transcript = stt_result.get("transcript", "").strip()
    if not transcript:
        # Return a friendly "didn't catch that" response with TTS
        no_speech_text = "I didn't catch that. Could you say it again?"
        try:
            tts_result = sarvam_service.generate_speech(
                text=no_speech_text, language="en-IN", speaker="kavya",
            )
        except Exception:
            tts_result = {"audio_base64": "", "format": "wav"}
        return {
            "transcript": "",
            "reply": no_speech_text,
            "voice_prompt": no_speech_text,
            "audio_base64": tts_result.get("audio_base64", ""),
            "session_id": session_id,
        }

    # --- Step 2: Chat Engine ---
    # Get or create chat session (same pattern as /chat/message in main.py)
    if session_id is None:
        session = crud.create_chat_session(db, current_user.id)
    else:
        session = (
            db.query(models.ChatSession)
            .filter(models.ChatSession.id == session_id)
            .first()
        )
        if not session or session.user_id != current_user.id:
            session = crud.create_chat_session(db, current_user.id)

    crud.add_chat_message(db, session.id, "user", transcript)
    result = chat.process_message(db, session, transcript)
    crud.add_chat_message(db, session.id, "bot", result["reply"])

    # --- Step 3: TTS ---
    voice_text = result.get("voice_prompt") or result.get("reply", "")
    # Truncate for TTS (Sarvam limit 2500 chars) and clean markdown
    import re
    voice_text = re.sub(r'\*\*|__|~~|`', '', voice_text)  # Strip markdown
    voice_text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', voice_text)  # Links
    voice_text = voice_text[:2000]  # Leave buffer for Sarvam

    audio_base64 = ""
    try:
        tts_result = sarvam_service.generate_speech(
            text=voice_text,
            language="en-IN",
            speaker="kavya",
        )
        audio_base64 = tts_result.get("audio_base64", "")
    except Exception as e:
        print(f"[VOICE] TTS failed (non-fatal): {e}")
        # Non-fatal — proceeed without audio

    return {
        "transcript": transcript,
        "reply": result.get("reply", ""),
        "voice_prompt": result.get("voice_prompt", ""),
        "audio_base64": audio_base64,
        "session_id": session.id,
        "restaurant_id": result.get("restaurant_id"),
        "category_id": result.get("category_id"),
        "order_id": result.get("order_id"),
        "categories": result.get("categories"),
        "items": result.get("items"),
        "cart_summary": result.get("cart_summary"),
    }

