"""
Voice endpoints for Sarvam AI STT + TTS + Conversation.
POST /api/voice/stt       — receive audio blob, return transcript
POST /api/voice/tts       — receive text, return base64 audio
POST /api/voice/chat      — receive text, return AI reply
POST /api/voice/converse  — full pipeline: audio → STT → chat engine → TTS → audio reply
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import sarvam_service, chat, crud, models
from .auth import get_current_user
from .db import get_db

router = APIRouter(prefix="/api/voice", tags=["voice"])


# ---------- STT ----------

@router.post("/stt")
async def speech_to_text(file: UploadFile = File(...)):
    """Transcribe uploaded audio using Sarvam Saaras v3."""
    audio_bytes = await file.read()
    if len(audio_bytes) == 0:
        raise HTTPException(400, "Empty audio file")
    if len(audio_bytes) > 10 * 1024 * 1024:  # 10MB max
        raise HTTPException(400, "Audio file too large (max 10MB)")

    try:
        result = sarvam_service.transcribe_audio(
            audio_bytes,
            filename=file.filename or "audio.webm",
        )
        return result
    except RuntimeError as e:
        raise HTTPException(502, str(e))


# ---------- TTS ----------

class TTSRequest(BaseModel):
    text: str
    language: str = "en-IN"
    speaker: str = "kavya"


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

    try:
        result = sarvam_service.generate_speech(
            text=req.text,
            language=req.language,
            speaker=req.speaker,
        )
        elapsed = (time.time() - t0) * 1000
        print(f"[TTS] \u23f1 {elapsed:.0f}ms | text=\"{req.text[:60]}{'...' if len(req.text) > 60 else ''}\"")
        return result
    except RuntimeError as e:
        raise HTTPException(502, str(e))


# ---------- Chat Agent ----------

class ChatRequest(BaseModel):
    message: str
    context: str = ""


def _is_group_order_intent(message: str) -> bool:
    """Detect if user is asking for group ordering (voice or text)."""
    import re
    lower = message.strip().lower()
    phrases = (
        "group order", "group ordering", "start a group order", "order as a group",
        "order for a group", "order together", "group food", "group lunch", "group dinner",
        "office lunch", "company lunch", "order for the team", "order for the office",
    )
    if any(p in lower for p in phrases):
        return True
    if re.search(r"(?:find|get|order|want|need)\s+(?:food|meals?|lunch|dinner)\s+for\s+\d+\s+people", lower):
        return True
    return False


@router.post("/chat")
async def voice_chat(req: ChatRequest):
    """Get intelligent response from Sarvam AI agent."""
    if not req.message.strip():
        raise HTTPException(400, "Message cannot be empty")

    # Group order intent: return fixed reply and signal frontend to open Group tab (no LLM call)
    if _is_group_order_intent(req.message):
        reply = (
            "I've opened the Group Order tab for you. Start a group order, share the link with friends, "
            "add their preferences, and get AI recommendations for the whole group!"
        )
        return {"reply": reply, "open_group_tab": True}

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
        "open_group_tab": result.get("open_group_tab"),
    }

