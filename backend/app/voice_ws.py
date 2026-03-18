"""
Real-time streaming voice gateway using Sarvam WebSocket APIs.

WebSocket endpoint: /ws/voice

Protocol (JSON messages + binary audio):
  Client → Server:
    {"type": "config", "session_id": 123, "token": "...", "restaurant_id": 5}
    <binary audio chunks>  (PCM 16-bit, 16kHz, mono)
    {"type": "interrupt"}   — barge-in: stop TTS

  Server → Client:
    {"type": "transcript", "text": "...", "final": false}
    {"type": "transcript", "text": "...", "final": true}
    {"type": "response", "text": "...", "categories": [...], "items": [...]}
    <binary audio chunks>  (WAV/PCM from Sarvam TTS)
    {"type": "tts_start"}
    {"type": "tts_end"}
    {"type": "error", "message": "..."}
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import struct
import wave
import io

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from . import chat, crud, models, sarvam_service
from .config import settings
from .db import SessionLocal

logger = logging.getLogger("voice_ws")

router = APIRouter(tags=["voice-streaming"])

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_STT_WS = "wss://api.sarvam.ai/speech-to-text/ws"
SARVAM_TTS_WS = "wss://api.sarvam.ai/text-to-speech/ws"


def _pcm_to_wav(pcm_data: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """Convert raw PCM data to WAV format."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


async def _sarvam_stt_rest(audio_bytes: bytes) -> str:
    """
    Fallback: Use Sarvam REST STT API.
    Streaming WebSocket is preferred but this works as a reliable fallback.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: sarvam_service.transcribe_audio(
            audio_bytes, filename="audio.wav"
        ),
    )
    return result.get("transcript", "")


async def _sarvam_tts_rest(text: str) -> bytes | None:
    """
    Use Sarvam REST TTS API to get audio.
    Returns raw WAV bytes or None.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: sarvam_service.generate_speech(text, language="en-IN", speaker="kavya"),
        )
        audio_b64 = result.get("audio_base64", "")
        if audio_b64:
            return base64.b64decode(audio_b64)
    except Exception as e:
        logger.error(f"TTS error: {e}")
    return None


async def _process_chat(
    session_id: int | None,
    user_id: int,
    text: str,
    restaurant_id: int | None = None,
) -> dict:
    """
    Process a chat message through the existing chat engine.
    Runs in executor since chat.process_message is synchronous.
    """
    import asyncio
    from .db import SessionLocal

    def _run():
        db = SessionLocal()
        try:
            if session_id:
                session = (
                    db.query(models.ChatSession)
                    .filter(models.ChatSession.id == session_id)
                    .first()
                )
                if not session or session.user_id != user_id:
                    session = crud.create_chat_session(db, user_id)
            else:
                session = crud.create_chat_session(db, user_id)

            crud.add_chat_message(db, session.id, "user", text)
            result = chat.process_message(db, session, text)
            crud.add_chat_message(db, session.id, "bot", result.get("reply", ""))

            return {
                "session_id": session.id,
                "reply": result.get("reply", ""),
                "categories": result.get("categories"),
                "items": result.get("items"),
                "cart_summary": result.get("cart_summary"),
            }
        finally:
            db.close()

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run)


@router.websocket("/ws/voice")
async def voice_stream(ws: WebSocket):
    """
    Real-time voice streaming endpoint.

    Flow:
    1. Client sends config message with token & session_id
    2. Client streams audio chunks (binary)
    3. Server accumulates audio, transcribes on silence
    4. Server processes through chat engine
    5. Server generates TTS and streams audio back
    """
    await ws.accept()
    logger.info("Voice WebSocket connected")

    # State
    config = {
        "token": None,
        "session_id": None,
        "user_id": None,
        "restaurant_id": None,
    }
    audio_buffer = bytearray()
    is_speaking = False  # True when TTS is playing
    tts_cancelled = False
    silence_task = None
    SILENCE_TIMEOUT = 1.0  # seconds of silence before processing

    async def process_audio():
        """Process accumulated audio buffer."""
        nonlocal audio_buffer, tts_cancelled

        if len(audio_buffer) < 3200:  # Less than 100ms of 16kHz audio
            return

        # Convert PCM to WAV for Sarvam
        wav_data = _pcm_to_wav(bytes(audio_buffer))
        audio_buffer.clear()

        try:
            # Transcribe
            transcript = await _sarvam_stt_rest(wav_data)

            if not transcript or not transcript.strip():
                return

            logger.info(f"Transcript: {transcript}")

            # Send final transcript to client
            await ws.send_json({
                "type": "transcript",
                "text": transcript,
                "final": True,
            })

            # Process through chat engine
            result = await _process_chat(
                session_id=config["session_id"],
                user_id=config["user_id"],
                text=transcript,
                restaurant_id=config.get("restaurant_id"),
            )

            # Update session_id
            if result.get("session_id"):
                config["session_id"] = result["session_id"]

            reply = result.get("reply", "")

            # Send text response
            await ws.send_json({
                "type": "response",
                "text": reply,
                "session_id": config["session_id"],
                "categories": result.get("categories"),
                "items": result.get("items"),
                "cart_summary": result.get("cart_summary"),
            })

            # Generate and stream TTS
            if reply and not tts_cancelled:
                await ws.send_json({"type": "tts_start"})

                # Split into sentences for faster first-chunk delivery
                import re
                sentences = re.split(r'(?<=[.!?])\s+', reply)
                sentences = [s.strip() for s in sentences if s.strip()]

                for sentence in sentences:
                    if tts_cancelled:
                        break

                    audio_data = await _sarvam_tts_rest(sentence)
                    if audio_data and not tts_cancelled:
                        # Send audio chunk as binary
                        await ws.send_bytes(audio_data)

                if not tts_cancelled:
                    await ws.send_json({"type": "tts_end"})

                tts_cancelled = False

        except Exception as e:
            logger.error(f"Processing error: {e}")
            await ws.send_json({"type": "error", "message": str(e)})

    try:
        while True:
            message = await ws.receive()

            if message.get("type") == "websocket.disconnect":
                break

            # Handle text messages (JSON)
            if "text" in message:
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type", "")

                if msg_type == "config":
                    # Authenticate and configure
                    token = data.get("token", "")
                    try:
                        payload = jwt.decode(
                            token,
                            settings.jwt_secret,
                            algorithms=[settings.jwt_algorithm],
                        )
                        email = payload.get("sub")
                        if not email:
                            raise ValueError("No sub in token")
                        # Look up user
                        db = SessionLocal()
                        try:
                            user = db.query(models.User).filter(models.User.email == email).first()
                            if not user:
                                raise ValueError(f"User not found: {email}")
                            config["user_id"] = user.id
                        finally:
                            db.close()
                        config["session_id"] = data.get("session_id")
                        config["restaurant_id"] = data.get("restaurant_id")
                        config["token"] = token
                        logger.info(f"Configured: user={config['user_id']}, session={config['session_id']}")
                        await ws.send_json({"type": "ready"})
                    except Exception as e:
                        await ws.send_json({"type": "error", "message": f"Auth failed: {e}"})

                elif msg_type == "interrupt":
                    # Barge-in: cancel TTS
                    tts_cancelled = True
                    logger.info("Barge-in: TTS cancelled")
                    await ws.send_json({"type": "interrupted"})

                elif msg_type == "process":
                    # Direct text processing (for text input via WS)
                    text = data.get("text", "").strip()
                    if text and config["user_id"]:
                        await process_audio.__wrapped__() if hasattr(process_audio, '__wrapped__') else None
                        # Process text directly
                        result = await _process_chat(
                            session_id=config["session_id"],
                            user_id=config["user_id"],
                            text=text,
                        )
                        if result.get("session_id"):
                            config["session_id"] = result["session_id"]

                        await ws.send_json({
                            "type": "response",
                            "text": result.get("reply", ""),
                            "session_id": config["session_id"],
                            "categories": result.get("categories"),
                            "items": result.get("items"),
                        })

                elif msg_type == "silence":
                    # Client detected silence — process audio buffer
                    if len(audio_buffer) > 3200:
                        await process_audio()

            # Handle binary messages (audio chunks)
            elif "bytes" in message:
                audio_chunk = message["bytes"]
                audio_buffer.extend(audio_chunk)

                # Send partial transcript feedback (every ~500ms worth of audio)
                if len(audio_buffer) > 16000:  # ~500ms at 16kHz
                    await ws.send_json({
                        "type": "listening",
                        "buffer_ms": len(audio_buffer) // 32,  # 16kHz * 2 bytes = 32 bytes/ms
                    })

    except WebSocketDisconnect:
        logger.info("Voice WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        logger.info("Voice WebSocket closed")
