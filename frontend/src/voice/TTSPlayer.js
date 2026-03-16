/**
 * TTSPlayer.js — Sentence-chunked streaming TTS with iOS audio priming
 * Splits text into sentences, generates TTS for each chunk,
 * plays first sentence immediately while pre-fetching rest.
 * Uses Sarvam Bulbul v3 (Indian accent, "kavya" speaker).
 *
 * iOS fix: Audio element is created eagerly and primed with a silent WAV
 * during a user gesture so subsequent play() calls succeed.
 */

import { vlog } from './VoiceDebugLogger.js';

const DEFAULT_SPEAKER = 'kavya';
const DEFAULT_LANG = 'en-IN';
const AUDIO_BUFFER_MS = 50;

const _isIOS = typeof navigator !== 'undefined' && /iPad|iPhone|iPod/.test(navigator.userAgent);

/**
 * Clean text for TTS (remove markdown, emoji, etc.)
 */
function cleanForTTS(text) {
    let clean = text
        .replace(/\*\*|__|~~|`/g, '')
        .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
        .replace(/#{1,6}\s*/g, '')
        .replace(/[🎤🍽️😊👋🔥📦⚠️⏳🌶️🍕🍔🍟🍣🍛🍰☕🍺🥤💧🍳🥞🧀🫔🧃🍵🍷🍸🍩🍪🍨🥧🍫🍎🍄🌽🍅✨🎙️🔊✕•]/g, '')
        .replace(/\n+/g, '. ')
        .replace(/\s+/g, ' ')
        .trim();
    return clean;
}

/**
 * Split text into speakable sentence chunks
 */
function splitIntoChunks(text) {
    const sentences = text.split(/(?<=[.!?])\s+/).filter(s => s.trim().length > 0);
    const chunks = [];
    let buffer = '';
    for (const sentence of sentences) {
        if (buffer.length + sentence.length < 150) {
            buffer = buffer ? buffer + ' ' + sentence : sentence;
        } else {
            if (buffer) chunks.push(buffer.trim());
            buffer = sentence;
        }
    }
    if (buffer.trim()) chunks.push(buffer.trim());
    if (chunks.length === 0 && text.trim()) {
        chunks.push(text.trim().substring(0, 2000));
    }
    return chunks;
}

/**
 * Generate TTS audio for a text chunk via Sarvam API
 */
async function generateChunkAudio(apiBase, text, speaker = DEFAULT_SPEAKER, lang = DEFAULT_LANG) {
    if (!text || text.trim().length < 2) return null;
    try {
        vlog('TTS', `fetch /api/voice/tts`, { text: text.substring(0, 50) });
        const resp = await fetch(`${apiBase}/api/voice/tts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text.substring(0, 2000), language: lang, speaker }),
        });
        if (!resp.ok) {
            vlog('ERR', `TTS fetch failed: ${resp.status}`);
            return null;
        }
        const data = await resp.json();
        vlog('TTS', `TTS audio received`, { hasAudio: !!data.audio_base64, len: (data.audio_base64 || '').length });
        return data.audio_base64 || null;
    } catch (err) {
        vlog('ERR', `TTS fetch error: ${err.message}`);
        return null;
    }
}

/**
 * Decode base64 audio → Blob URL
 */
function decodeAudioBase64(base64) {
    const bytes = atob(base64);
    const buffer = new Uint8Array(bytes.length);
    for (let i = 0; i < bytes.length; i++) buffer[i] = bytes.charCodeAt(i);
    const blob = new Blob([buffer], { type: 'audio/wav' });
    return URL.createObjectURL(blob);
}

/**
 * TTSPlayer class — manages streaming TTS playback
 */
export class TTSPlayer {
    constructor(apiBase) {
        this.apiBase = apiBase;
        // Create Audio element eagerly so it can be primed during user gesture
        this.audioEl = new Audio();
        this.currentUrls = [];
        this.isPlaying = false;
        this.isCancelled = false;
        this._primed = false;
        this.onStateChange = null;
        this.onChunkStart = null;
        this.onComplete = null;
        vlog('TTS', 'TTSPlayer constructed', { iOS: _isIOS });
    }

    /**
     * Prime the Audio element for iOS — MUST be called during a user gesture (tap).
     * Plays a tiny silent WAV so iOS marks this Audio element as gesture-allowed.
     */
    primeForIOS() {
        if (this._primed) return;
        try {
            const silentWav = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=';
            this.audioEl.src = silentWav;
            this.audioEl.volume = 0.01;
            const playPromise = this.audioEl.play();
            if (playPromise) {
                playPromise.then(() => {
                    this.audioEl.pause();
                    this.audioEl.currentTime = 0;
                    this.audioEl.volume = 1.0;
                    this._primed = true;
                    vlog('IOS', 'Audio element PRIMED successfully');
                }).catch((err) => {
                    vlog('ERR', `Audio prime failed: ${err.message}`);
                });
            }
        } catch (err) {
            vlog('ERR', `Audio prime error: ${err.message}`);
        }
    }

    /**
     * Play text with sentence-chunked streaming TTS
     */
    async speak(text, { speaker = DEFAULT_SPEAKER, lang = DEFAULT_LANG } = {}) {
        this.stop();
        this.isCancelled = false;
        this.isPlaying = true;

        const clean = cleanForTTS(text);
        vlog('TTS', `speak() called`, { cleanLen: clean.length, iOS: _isIOS, primed: this._primed });

        if (!clean) {
            this.isPlaying = false;
            this.onComplete?.();
            return;
        }

        const chunks = splitIntoChunks(clean);
        if (chunks.length === 0) {
            this.isPlaying = false;
            this.onComplete?.();
            return;
        }

        this.onStateChange?.('speaking');
        vlog('TTS', `${chunks.length} chunk(s) to speak`);

        // Pre-fetch ALL chunks in parallel (but play sequentially)
        const audioPromises = chunks.map(chunk => generateChunkAudio(this.apiBase, chunk, speaker, lang));

        // Play chunks sequentially as they resolve
        for (let i = 0; i < chunks.length; i++) {
            if (this.isCancelled) break;

            const audioBase64 = await audioPromises[i];
            if (this.isCancelled || !audioBase64) continue;

            this.onChunkStart?.(i, chunks.length);
            vlog('TTS', `Playing chunk ${i + 1}/${chunks.length}`);
            await this._playAudioChunk(audioBase64);
        }

        // Cleanup
        this.isPlaying = false;
        this.currentUrls.forEach(url => URL.revokeObjectURL(url));
        this.currentUrls = [];

        if (!this.isCancelled) {
            vlog('TTS', 'All chunks played, calling onComplete');
            this.onStateChange?.('idle');
            this.onComplete?.();
        }
    }

    /**
     * Play a single audio chunk
     */
    _playAudioChunk(base64) {
        return new Promise((resolve) => {
            if (this.isCancelled) { resolve(); return; }

            const url = decodeAudioBase64(base64);
            this.currentUrls.push(url);

            const audio = this.audioEl;
            audio.src = url;

            audio.onended = () => {
                vlog('TTS', 'chunk audio.onended');
                resolve();
            };
            audio.onerror = (e) => {
                vlog('ERR', `chunk audio.onerror: ${e?.type || 'unknown'}`);
                resolve();
            };

            // iOS: call load() explicitly before play() for better compatibility
            if (_isIOS) {
                audio.load();
            }

            setTimeout(() => {
                if (this.isCancelled) { resolve(); return; }
                const playPromise = audio.play();
                if (playPromise) {
                    playPromise.then(() => {
                        vlog('TTS', 'audio.play() SUCCESS');
                    }).catch((err) => {
                        vlog('ERR', `audio.play() BLOCKED: ${err.message}`);
                        resolve();
                    });
                }
            }, AUDIO_BUFFER_MS);
        });
    }

    /**
     * Stop playback immediately (for barge-in)
     */
    stop() {
        this.isCancelled = true;
        this.isPlaying = false;
        if (this.audioEl) {
            this.audioEl.pause();
            this.audioEl.currentTime = 0;
        }
        this.currentUrls.forEach(url => URL.revokeObjectURL(url));
        this.currentUrls = [];
    }

    /**
     * Destroy player and cleanup
     */
    destroy() {
        this.stop();
        this.audioEl = null;
        this.onStateChange = null;
        this.onChunkStart = null;
        this.onComplete = null;
    }
}

export default TTSPlayer;
