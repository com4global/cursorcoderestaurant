/**
 * TTSPlayer.js — TTS playback with iOS fallback chain
 *
 * Playback strategy (tries in order):
 * 1. AudioContext + decodeAudioData (callback form for iOS compat)
 * 2. Audio element with data:audio/wav;base64 URI (fallback)
 * 3. Skip chunk and continue (graceful degradation)
 */

import { vlog } from './VoiceDebugLogger.js';

const DEFAULT_SPEAKER = 'kavya';
const DEFAULT_LANG = 'en-IN';
const _isIOS = typeof navigator !== 'undefined' && /iPad|iPhone|iPod/.test(navigator.userAgent);

function cleanForTTS(text) {
    return text
        .replace(/\*\*|__|~~|`/g, '')
        .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
        .replace(/#{1,6}\s*/g, '')
        .replace(/[🎤🍽️😊👋🔥📦⚠️⏳🌶️🍕🍔🍟🍣🍛🍰☕🍺🥤💧🍳🥞🧀🫔🧃🍵🍷🍸🍩🍪🍨🥧🍫🍎🍄🌽🍅✨🎙️🔊✕•]/g, '')
        .replace(/\n+/g, '. ')
        .replace(/\s+/g, ' ')
        .trim();
}

function splitIntoChunks(text) {
    const sentences = text.split(/(?<=[.!?])\s+/).filter(s => s.trim().length > 0);
    const chunks = [];
    let buffer = '';
    for (const sentence of sentences) {
        if (buffer.length + sentence.length < 500) {
            buffer = buffer ? buffer + ' ' + sentence : sentence;
        } else {
            if (buffer) chunks.push(buffer.trim());
            buffer = sentence;
        }
    }
    if (buffer.trim()) chunks.push(buffer.trim());
    if (chunks.length === 0 && text.trim()) chunks.push(text.trim().substring(0, 2000));
    return chunks;
}

async function generateChunkAudio(apiBase, text, speaker = DEFAULT_SPEAKER, lang = DEFAULT_LANG) {
    if (!text || text.trim().length < 2) return null;
    try {
        vlog('TTS', `fetch /api/voice/tts`, { text: text.substring(0, 50) });
        const resp = await fetch(`${apiBase}/api/voice/tts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text.substring(0, 2000), language: lang, speaker }),
        });
        if (!resp.ok) { vlog('ERR', `TTS fetch: ${resp.status}`); return null; }
        const data = await resp.json();
        vlog('TTS', `audio received`, { len: (data.audio_base64 || '').length });
        return data.audio_base64 || null;
    } catch (err) {
        vlog('ERR', `TTS fetch error: ${err.message}`);
        return null;
    }
}

function base64ToArrayBuffer(base64) {
    const bin = atob(base64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes.buffer;
}

export class TTSPlayer {
    constructor(apiBase) {
        this.apiBase = apiBase;
        this._audioCtx = null;
        this._currentSource = null;
        this._currentAudio = null;
        this.isPlaying = false;
        this.isCancelled = false;
        this.onStateChange = null;
        this.onChunkStart = null;
        this.onComplete = null;
        vlog('TTS', 'TTSPlayer constructed', { iOS: _isIOS });
    }

    _getAudioContext() {
        if (!this._audioCtx) {
            const AC = window.AudioContext || window.webkitAudioContext;
            if (!AC) return null;
            this._audioCtx = new AC();
            vlog('TTS', `AudioContext created: ${this._audioCtx.state}`);
        }
        return this._audioCtx;
    }

    /**
     * Prime audio during user gesture tap — CRITICAL for iOS
     */
    primeForIOS() {
        const ctx = this._getAudioContext();
        if (!ctx) return;

        // Resume AudioContext
        if (ctx.state === 'suspended') {
            ctx.resume().then(() => vlog('IOS', `AudioContext resumed: ${ctx.state}`))
                .catch(e => vlog('ERR', `resume fail: ${e.message}`));
        } else {
            vlog('IOS', `AudioContext already: ${ctx.state}`);
        }

        // Play silent buffer to fully unlock audio pipeline
        try {
            const buf = ctx.createBuffer(1, 1, ctx.sampleRate);
            const src = ctx.createBufferSource();
            src.buffer = buf;
            src.connect(ctx.destination);
            src.start(0);
            vlog('IOS', 'Silent buffer primed');
        } catch (e) {
            vlog('ERR', `prime fail: ${e.message}`);
        }

        // ALSO prime an Audio element (belt + suspenders approach)
        try {
            const a = new Audio('data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=');
            a.volume = 0.01;
            a.play().then(() => { a.pause(); vlog('IOS', 'Audio element primed'); })
                .catch(() => vlog('IOS', 'Audio element prime skipped'));
        } catch (_) { }
    }

    async speak(text, { speaker = DEFAULT_SPEAKER, lang = DEFAULT_LANG } = {}) {
        this.stop();
        this.isCancelled = false;
        this.isPlaying = true;

        const clean = cleanForTTS(text);
        vlog('TTS', `speak()`, { cleanLen: clean.length });

        if (!clean) { this.isPlaying = false; this.onComplete?.(); return; }

        const chunks = splitIntoChunks(clean);
        if (chunks.length === 0) { this.isPlaying = false; this.onComplete?.(); return; }

        this.onStateChange?.('speaking');
        vlog('TTS', `${chunks.length} chunk(s)`);

        // Pre-fetch all chunks
        const audioPromises = chunks.map(c => generateChunkAudio(this.apiBase, c, speaker, lang));

        for (let i = 0; i < chunks.length; i++) {
            if (this.isCancelled) break;
            const audioBase64 = await audioPromises[i];
            if (this.isCancelled || !audioBase64) continue;
            this.onChunkStart?.(i, chunks.length);
            vlog('TTS', `Playing chunk ${i + 1}/${chunks.length}`);
            await this._playAudioChunk(audioBase64);
        }

        this.isPlaying = false;
        this._currentSource = null;
        this._currentAudio = null;

        if (!this.isCancelled) {
            vlog('TTS', 'All done → onComplete');
            this.onStateChange?.('idle');
            this.onComplete?.();
        }
    }

    /**
     * Play audio chunk — tries AudioContext first, falls back to Audio element
     */
    async _playAudioChunk(base64) {
        if (this.isCancelled) return;

        // METHOD 1: Try AudioContext + decodeAudioData (callback form for iOS)
        const ctx = this._audioCtx;
        if (ctx && ctx.state === 'running') {
            try {
                const arrayBuf = base64ToArrayBuffer(base64);
                const played = await this._playViaAudioContext(ctx, arrayBuf);
                if (played) return; // Success!
            } catch (err) {
                vlog('ERR', `AudioContext play failed: ${err.message}`);
            }
        } else {
            vlog('TTS', `AudioContext not ready: ${ctx?.state || 'null'}`);
        }

        // METHOD 2: Fallback to Audio element with data URI
        vlog('TTS', 'Falling back to Audio element');
        await this._playViaAudioElement(base64);
    }

    /**
     * Play via AudioContext using CALLBACK form of decodeAudioData (iOS compatible)
     */
    _playViaAudioContext(ctx, arrayBuffer) {
        return new Promise((resolve) => {
            if (this.isCancelled) { resolve(false); return; }

            // Use CALLBACK form — the Promise form silently fails on some iOS versions
            ctx.decodeAudioData(
                arrayBuffer,
                (audioBuffer) => {
                    if (this.isCancelled) { resolve(false); return; }
                    vlog('TTS', `decoded: ${audioBuffer.duration.toFixed(1)}s`);

                    const source = ctx.createBufferSource();
                    source.buffer = audioBuffer;
                    source.connect(ctx.destination);
                    source.playbackRate.value = 1.1;  // Slightly faster speech
                    this._currentSource = source;

                    source.onended = () => {
                        vlog('TTS', 'chunk ended');
                        resolve(true);
                    };

                    try {
                        source.start(0);
                        vlog('TTS', 'AudioContext: playing ✓');
                    } catch (e) {
                        vlog('ERR', `source.start fail: ${e.message}`);
                        resolve(false);
                    }
                },
                (err) => {
                    vlog('ERR', `decodeAudioData fail: ${err?.message || err}`);
                    resolve(false);
                }
            );
        });
    }

    /**
     * Fallback: play via Audio element with data URI
     */
    _playViaAudioElement(base64) {
        return new Promise((resolve) => {
            if (this.isCancelled) { resolve(); return; }
            try {
                const audio = new Audio('data:audio/wav;base64,' + base64);
                this._currentAudio = audio;
                audio.onended = () => { vlog('TTS', 'Audio element ended'); resolve(); };
                audio.onerror = (e) => { vlog('ERR', `Audio element error: ${e.type}`); resolve(); };
                const playPromise = audio.play();
                if (playPromise) {
                    playPromise.then(() => vlog('TTS', 'Audio element: playing ✓'))
                        .catch(e => { vlog('ERR', `Audio.play() blocked: ${e.message}`); resolve(); });
                }
            } catch (e) {
                vlog('ERR', `Audio fallback fail: ${e.message}`);
                resolve();
            }
        });
    }

    stop() {
        this.isCancelled = true;
        this.isPlaying = false;
        if (this._currentSource) { try { this._currentSource.stop(); } catch (_) { } this._currentSource = null; }
        if (this._currentAudio) { try { this._currentAudio.pause(); this._currentAudio.src = ''; } catch (_) { } this._currentAudio = null; }
    }

    destroy() {
        this.stop();
        if (this._audioCtx) { try { this._audioCtx.close(); } catch (_) { } this._audioCtx = null; }
        this.onStateChange = null;
        this.onChunkStart = null;
        this.onComplete = null;
    }
}

export default TTSPlayer;
