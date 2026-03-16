/**
 * TTSPlayer.js — Sentence-chunked streaming TTS using AudioContext (iOS-safe)
 *
 * Uses Web Audio API (AudioContext) instead of <audio> element because:
 * - AudioContext.resume() only needs ONE user gesture, then all subsequent
 *   audio plays work (even async). Audio elements lose gesture context on src change.
 * - Works in WKWebView (Tauri iOS) where <audio> behavior is very restricted.
 *
 * Uses Sarvam Bulbul v3 (Indian accent, "kavya" speaker).
 */

import { vlog } from './VoiceDebugLogger.js';

const DEFAULT_SPEAKER = 'kavya';
const DEFAULT_LANG = 'en-IN';

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
 * Split text into speakable sentence chunks (10-150 chars)
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
 * Decode base64 string to ArrayBuffer for AudioContext.decodeAudioData
 */
function base64ToArrayBuffer(base64) {
    const binaryStr = atob(base64);
    const len = binaryStr.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) bytes[i] = binaryStr.charCodeAt(i);
    return bytes.buffer;
}

/**
 * TTSPlayer class — manages streaming TTS playback via AudioContext
 */
export class TTSPlayer {
    constructor(apiBase) {
        this.apiBase = apiBase;
        this._audioCtx = null;
        this._currentSource = null;
        this.isPlaying = false;
        this.isCancelled = false;
        this._primed = false;
        this.onStateChange = null;
        this.onChunkStart = null;
        this.onComplete = null;
        vlog('TTS', 'TTSPlayer constructed (AudioContext mode)', { iOS: _isIOS });
    }

    /**
     * Get or create AudioContext. Lazily created so it can be resumed during user gesture.
     */
    _getAudioContext() {
        if (!this._audioCtx) {
            const AC = window.AudioContext || window.webkitAudioContext;
            if (!AC) {
                vlog('ERR', 'AudioContext not supported');
                return null;
            }
            this._audioCtx = new AC();
            vlog('TTS', `AudioContext created, state: ${this._audioCtx.state}`);
        }
        return this._audioCtx;
    }

    /**
     * Prime AudioContext for iOS — MUST be called during a user gesture (tap).
     * This resumes the AudioContext (iOS suspends it by default) so all
     * subsequent audio plays work without needing another gesture.
     */
    primeForIOS() {
        const ctx = this._getAudioContext();
        if (!ctx) return;

        if (ctx.state === 'suspended') {
            ctx.resume().then(() => {
                this._primed = true;
                vlog('IOS', `AudioContext RESUMED: ${ctx.state}`);
            }).catch(err => {
                vlog('ERR', `AudioContext resume failed: ${err.message}`);
            });
        } else {
            this._primed = true;
            vlog('IOS', `AudioContext already running: ${ctx.state}`);
        }

        // Also play a tiny silent buffer to fully unlock the audio pipeline
        try {
            const buf = ctx.createBuffer(1, 1, ctx.sampleRate);
            const src = ctx.createBufferSource();
            src.buffer = buf;
            src.connect(ctx.destination);
            src.start(0);
            vlog('IOS', 'Silent buffer played to prime audio pipeline');
        } catch (e) {
            vlog('ERR', `Silent buffer prime failed: ${e.message}`);
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
        vlog('TTS', `speak()`, { cleanLen: clean.length, primed: this._primed });

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

        // Ensure AudioContext is created and resumed
        const ctx = this._getAudioContext();
        if (!ctx) {
            vlog('ERR', 'No AudioContext — skipping TTS');
            this.isPlaying = false;
            this.onComplete?.();
            return;
        }
        if (ctx.state === 'suspended') {
            try { await ctx.resume(); } catch (_) { }
            vlog('TTS', `AudioContext state after resume attempt: ${ctx.state}`);
        }

        // Pre-fetch ALL chunks in parallel
        const audioPromises = chunks.map(chunk => generateChunkAudio(this.apiBase, chunk, speaker, lang));

        // Play chunks sequentially
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
        this._currentSource = null;

        if (!this.isCancelled) {
            vlog('TTS', 'All chunks played, calling onComplete');
            this.onStateChange?.('idle');
            this.onComplete?.();
        }
    }

    /**
     * Play a single audio chunk via AudioContext (no Audio element needed)
     */
    _playAudioChunk(base64) {
        return new Promise(async (resolve) => {
            if (this.isCancelled) { resolve(); return; }

            const ctx = this._audioCtx;
            if (!ctx) { resolve(); return; }

            try {
                const arrayBuffer = base64ToArrayBuffer(base64);
                const audioBuffer = await ctx.decodeAudioData(arrayBuffer);

                if (this.isCancelled) { resolve(); return; }

                const source = ctx.createBufferSource();
                source.buffer = audioBuffer;
                source.connect(ctx.destination);
                this._currentSource = source;

                source.onended = () => {
                    vlog('TTS', 'chunk onended');
                    resolve();
                };

                source.start(0);
                vlog('TTS', 'AudioContext source.start() SUCCESS');
            } catch (err) {
                vlog('ERR', `AudioContext play error: ${err.message}`);
                resolve();
            }
        });
    }

    /**
     * Stop playback immediately (for barge-in)
     */
    stop() {
        this.isCancelled = true;
        this.isPlaying = false;
        if (this._currentSource) {
            try { this._currentSource.stop(); } catch (_) { }
            this._currentSource = null;
        }
    }

    /**
     * Destroy player and cleanup
     */
    destroy() {
        this.stop();
        if (this._audioCtx) {
            try { this._audioCtx.close(); } catch (_) { }
            this._audioCtx = null;
        }
        this.onStateChange = null;
        this.onChunkStart = null;
        this.onComplete = null;
    }
}

export default TTSPlayer;
