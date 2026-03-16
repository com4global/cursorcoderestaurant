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

# ---------- STT Trace Log (persisted to DB) ----------
import time as _time
from datetime import datetime


def _ensure_voice_log_table():
    """Auto-create voice_logs table if it doesn't exist."""
    try:
        from .db import engine
        models.VoiceLog.__table__.create(engine, checkfirst=True)
    except Exception as e:
        print(f"[VoiceLog] Table create skipped: {e}")


@router.get("/stt-log")
async def get_stt_log(limit: int = 30, db: Session = Depends(get_db)):
    """Retrieve recent STT call logs from database for debugging."""
    _ensure_voice_log_table()
    try:
        logs = (
            db.query(models.VoiceLog)
            .order_by(models.VoiceLog.id.desc())
            .limit(limit)
            .all()
        )
        return {
            "count": len(logs),
            "logs": [
                {
                    "id": log.id,
                    "ts": log.timestamp.strftime("%H:%M:%S") if log.timestamp else None,
                    "filename": log.filename,
                    "content_type": log.content_type,
                    "audio_kb": log.audio_kb,
                    "language": log.language,
                    "transcript": log.transcript,
                    "detected_lang": log.detected_lang,
                    "duration_ms": log.duration_ms,
                    "error": log.error,
                }
                for log in logs
            ],
        }
    except Exception as e:
        return {"count": 0, "logs": [], "error": str(e)}


# ---------- STT ----------

@router.post("/stt")
async def speech_to_text(file: UploadFile = File(...), language: str = Form("en-IN"), db: Session = Depends(get_db)):
    """Transcribe uploaded audio using Sarvam Saaras v3."""
    _ensure_voice_log_table()
    t0 = _time.time()
    audio_bytes = await file.read()
    filename = file.filename or "audio.webm"
    content_type = file.content_type or "unknown"
    audio_kb = len(audio_bytes) / 1024

    log = models.VoiceLog(
        timestamp=datetime.utcnow(),
        filename=filename,
        content_type=content_type,
        audio_kb=round(audio_kb, 1),
        language=language,
    )

    print(f"[STT] ← {audio_kb:.1f}KB | file={filename} | type={content_type} | lang={language}")

    if len(audio_bytes) == 0:
        log.error = "Empty audio"
        db.add(log); db.commit()
        raise HTTPException(400, "Empty audio file")
    if len(audio_bytes) > 10 * 1024 * 1024:
        log.error = "Too large"
        db.add(log); db.commit()
        raise HTTPException(400, "Audio file too large (max 10MB)")

    try:
        result = sarvam_service.transcribe_audio(
            audio_bytes,
            filename=filename,
            language_code=language,
        )
        elapsed = (_time.time() - t0) * 1000
        transcript = result.get("transcript", "")
        detected = result.get("language", "")

        log.transcript = transcript
        log.detected_lang = detected
        log.duration_ms = round(elapsed)
        db.add(log); db.commit()

        print(f"[STT] → \"{transcript}\" | detected={detected} | ⏱{elapsed:.0f}ms")
        return result
    except RuntimeError as e:
        elapsed = (_time.time() - t0) * 1000
        log.error = str(e)[:500]
        log.duration_ms = round(elapsed)
        db.add(log); db.commit()
        print(f"[STT] ✗ {str(e)[:100]} | ⏱{elapsed:.0f}ms")
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


@router.post("/chat")
async def voice_chat(req: ChatRequest):
    """Get intelligent response from Sarvam AI agent."""
    if not req.message.strip():
        raise HTTPException(400, "Message cannot be empty")

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

