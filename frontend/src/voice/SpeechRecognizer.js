/**
 * SpeechRecognizer.js — Browser speech recognition with iOS + WKWebView fallback
 *
 * Strategy:
 * - Desktop Chrome/Safari: Use native webkitSpeechRecognition (continuous=true)
 * - iOS Safari/Chrome: Use native webkitSpeechRecognition (continuous=false, single-shot)
 * - WKWebView (Tauri iOS): SpeechRecognition doesn't exist → fallback to
 *   MediaRecorder + backend /api/voice/stt (Sarvam Saaras STT)
 */

import { vlog } from './VoiceDebugLogger.js';

const DEBOUNCE_MS = 1000;

const _isIOS = typeof navigator !== 'undefined' && /iPad|iPhone|iPod/.test(navigator.userAgent);
const _isSafari = typeof navigator !== 'undefined' && /^((?!chrome|android).)*safari/i.test(navigator.userAgent);
const _isIOSWebKit = _isIOS || (_isSafari && typeof document !== 'undefined' && 'ontouchend' in document);

export class SpeechRecognizer {
    constructor(options = {}) {
        this.recognition = null;
        this.debounceTimer = null;
        this.finalTranscript = '';
        this.isListening = false;
        this.lang = options.lang || 'en-IN';
        this.apiBase = options.apiBase || '';
        this.keepListeningOnFinal = options.keepListeningOnFinal === true;
        this._intentionallyStopped = false;
        this._useFallback = false;  // true when using MediaRecorder fallback
        this._mediaRecorder = null;
        this._audioChunks = [];
        this._mediaStream = null;

        // Callbacks
        this.onLiveTranscript = null;
        this.onFinalTranscript = null;
        this.onStateChange = null;
        this.onError = null;
        this.onSpeechDetected = null;
    }

    /**
     * Check if any form of speech recognition is available
     */
    static isSupported() {
        // Native Web Speech API
        if (window.SpeechRecognition || window.webkitSpeechRecognition) return true;
        // Fallback: MediaRecorder for backend STT
        if (navigator.mediaDevices && typeof MediaRecorder !== 'undefined') return true;
        return false;
    }

    /**
     * Start listening — uses native API or MediaRecorder fallback
     */
    start() {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

        if (SR) {
            this._useFallback = false;
            return this._startNative(SR);
        }

        // Fallback: use MediaRecorder + backend STT
        if (navigator.mediaDevices && typeof MediaRecorder !== 'undefined') {
            vlog('IOS', 'No SpeechRecognition API — using MediaRecorder fallback');
            this._useFallback = true;
            return this._startMediaRecorder();
        }

        vlog('ERR', 'No speech recognition available');
        this.onError?.('Speech recognition not supported in this browser');
        return false;
    }

    /**
     * Start using native SpeechRecognition
     */
    _startNative(SR) {
        this.stop();
        this.finalTranscript = '';
        this._intentionallyStopped = false;

        const recognition = new SR();

        if (_isIOSWebKit) {
            recognition.continuous = false;
            recognition.interimResults = false;
            vlog('IOS', 'Native STT: single-shot mode');
        } else {
            recognition.continuous = true;
            recognition.interimResults = true;
        }

        recognition.lang = this.lang;
        recognition.maxAlternatives = 1;
        this.recognition = recognition;

        recognition.onstart = () => {
            this.isListening = true;
            vlog('STT', 'recognition.onstart', { lang: this.lang, iOS: _isIOSWebKit });
            this.onStateChange?.('listening');
        };

        recognition.onresult = (event) => {
            let interim = '';
            let final = '';
            let confidenceSum = 0;
            let confidenceCount = 0;

            for (let i = event.resultIndex; i < event.results.length; i++) {
                const transcript = event.results[i][0].transcript;
                const conf = event.results[i][0].confidence || 0;
                if (event.results[i].isFinal) {
                    final += transcript;
                    confidenceSum += conf;
                    confidenceCount++;
                } else {
                    interim += transcript;
                }
            }

            vlog('STT', 'onresult', {
                final: final || '(none)',
                interim: interim || '(none)',
                confidence: confidenceCount > 0 ? (confidenceSum / confidenceCount).toFixed(2) : 'N/A'
            });

            if (final) {
                this.finalTranscript = (this.finalTranscript + ' ' + final).trim();
            }
            if (confidenceCount > 0) {
                this._lastConfidence = confidenceSum / confidenceCount;
            }
            this._lastInterim = interim;
            this.onSpeechDetected?.();

            const display = (this.finalTranscript + ' ' + interim).trim();
            this.onLiveTranscript?.(display);

            // iOS single-shot: send immediately
            if (_isIOSWebKit && final) {
                const textToSend = this.finalTranscript.trim();
                const confidence = this._lastConfidence || 0;
                vlog('IOS', 'Single-shot final → sending', { text: textToSend });
                this.finalTranscript = '';
                this._lastInterim = '';
                this._lastConfidence = 0;
                this.onLiveTranscript?.('');
                this.onFinalTranscript?.(textToSend, confidence);
                return;
            }

            // Desktop: debounce
            clearTimeout(this.debounceTimer);
            this.debounceTimer = setTimeout(() => {
                const pending = this._lastInterim?.trim() || '';
                const textToSend = (this.finalTranscript.trim() + (pending ? ' ' + pending : '')).trim();
                const confidence = this._lastConfidence || 0;
                if (textToSend) {
                    this.finalTranscript = '';
                    this._lastInterim = '';
                    this._lastConfidence = 0;
                    this.onLiveTranscript?.('');
                    if (!this.keepListeningOnFinal) this.stop();
                    this.onFinalTranscript?.(textToSend, confidence);
                }
            }, DEBOUNCE_MS);
        };

        recognition.onerror = (e) => {
            this.isListening = false;
            vlog('ERR', `recognition.onerror: ${e.error}`);

            if (e.error === 'no-speech') {
                if (!_isIOSWebKit) {
                    setTimeout(() => this.start(), 500);
                } else {
                    this.onStateChange?.('idle');
                }
            } else if (e.error === 'aborted') {
                // Intentional
            } else if (e.error === 'not-allowed') {
                this.onError?.('Microphone blocked — enable in browser settings');
                this.onStateChange?.('idle');
            } else {
                this.onError?.('Mic error: ' + e.error);
                if (!_isIOSWebKit) {
                    setTimeout(() => this.start(), 1000);
                } else {
                    this.onStateChange?.('idle');
                }
            }
        };

        recognition.onend = () => {
            this.isListening = false;
            vlog('STT', 'recognition.onend', { stopped: this._intentionallyStopped, iOS: _isIOSWebKit });

            if (_isIOSWebKit) {
                this.onStateChange?.('idle');
                return;
            }

            if (this.recognition === recognition && !this._intentionallyStopped) {
                setTimeout(() => {
                    if (this.recognition === recognition && !this._intentionallyStopped) {
                        this.start();
                    }
                }, 300);
            }
        };

        try {
            recognition.start();
            vlog('STT', 'recognition.start() called');
            return true;
        } catch (err) {
            vlog('ERR', `recognition.start() FAILED: ${err.message}`);
            this.onStateChange?.('idle');
            return false;
        }
    }

    /**
     * Fallback: Record audio with MediaRecorder, send to backend /api/voice/stt
     * Used in WKWebView where SpeechRecognition doesn't exist.
     */
    async _startMediaRecorder() {
        this.stop();
        this._intentionallyStopped = false;
        this._audioChunks = [];

        try {
            // Request mic if we don't have a stream yet
            if (!this._mediaStream) {
                this._mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                vlog('MIC', 'MediaRecorder: mic stream acquired');
            }

            // Determine supported MIME type
            let mimeType = 'audio/webm';
            if (typeof MediaRecorder.isTypeSupported === 'function') {
                if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
                    mimeType = 'audio/webm;codecs=opus';
                } else if (MediaRecorder.isTypeSupported('audio/mp4')) {
                    mimeType = 'audio/mp4';
                } else if (MediaRecorder.isTypeSupported('audio/wav')) {
                    mimeType = 'audio/wav';
                }
            }
            vlog('MIC', `MediaRecorder mime: ${mimeType}`);

            const recorder = new MediaRecorder(this._mediaStream, { mimeType });
            this._mediaRecorder = recorder;

            recorder.ondataavailable = (e) => {
                if (e.data.size > 0) this._audioChunks.push(e.data);
            };

            recorder.onstop = async () => {
                if (this._intentionallyStopped || this._audioChunks.length === 0) {
                    vlog('MIC', 'MediaRecorder stopped (no data or intentional)');
                    this.isListening = false;
                    this.onStateChange?.('idle');
                    return;
                }

                const fileExt = mimeType.includes('mp4') ? 'audio.mp4' : mimeType.includes('wav') ? 'audio.wav' : 'audio.webm';
                const blob = new Blob(this._audioChunks, { type: mimeType });
                this._audioChunks = [];
                vlog('MIC', `Sending ${(blob.size / 1024).toFixed(1)}KB to backend STT`);

                // Send to backend
                const formData = new FormData();
                formData.append('file', blob, fileExt);

                try {
                    const resp = await fetch(`${this.apiBase}/api/voice/stt`, {
                        method: 'POST',
                        body: formData,
                    });
                    if (resp.ok) {
                        const data = await resp.json();
                        const transcript = (data.transcript || '').trim();
                        vlog('STT', `Backend STT result: "${transcript}"`);
                        if (transcript) {
                            this.onLiveTranscript?.(transcript);
                            this.onFinalTranscript?.(transcript, 0.8);
                        } else {
                            vlog('STT', 'Empty transcript from backend');
                            this.onStateChange?.('idle');
                        }
                    } else {
                        vlog('ERR', `Backend STT failed: ${resp.status}`);
                        this.onStateChange?.('idle');
                    }
                } catch (err) {
                    vlog('ERR', `Backend STT error: ${err.message}`);
                    this.onStateChange?.('idle');
                }

                this.isListening = false;
            };

            recorder.onerror = (e) => {
                vlog('ERR', `MediaRecorder error: ${e.error?.message || 'unknown'}`);
                this.isListening = false;
                this.onStateChange?.('idle');
            };

            // Start recording — stop after 5 seconds of silence or max 8 seconds
            recorder.start();
            this.isListening = true;
            this.onStateChange?.('listening');
            this.onLiveTranscript?.('🎤 Listening...');
            vlog('MIC', 'MediaRecorder started (auto-stop in 6s)');

            // Auto-stop after 6 seconds (single utterance)
            this._recorderTimeout = setTimeout(() => {
                if (recorder.state === 'recording') {
                    vlog('MIC', 'Auto-stopping MediaRecorder after timeout');
                    recorder.stop();
                }
            }, 6000);

            return true;
        } catch (err) {
            vlog('ERR', `MediaRecorder start failed: ${err.message}`);
            this.onError?.('Mic error: ' + err.message);
            this.onStateChange?.('idle');
            return false;
        }
    }

    /**
     * Manually stop recording (user taps again or speaks enough)
     */
    stopRecording() {
        if (this._mediaRecorder && this._mediaRecorder.state === 'recording') {
            clearTimeout(this._recorderTimeout);
            this._mediaRecorder.stop();
            vlog('MIC', 'MediaRecorder manually stopped');
        }
    }

    setLang(lang) {
        this.lang = lang || 'en-IN';
    }

    stop() {
        clearTimeout(this.debounceTimer);
        clearTimeout(this._recorderTimeout);
        this.isListening = false;
        this._intentionallyStopped = true;

        if (this.recognition) {
            try { this.recognition.abort(); } catch { }
            this.recognition = null;
        }
        if (this._mediaRecorder && this._mediaRecorder.state === 'recording') {
            try { this._mediaRecorder.stop(); } catch { }
        }
        this._mediaRecorder = null;
    }

    destroy() {
        this.stop();
        if (this._mediaStream) {
            this._mediaStream.getTracks().forEach(t => t.stop());
            this._mediaStream = null;
        }
        this.onLiveTranscript = null;
        this.onFinalTranscript = null;
        this.onStateChange = null;
        this.onError = null;
        this.onSpeechDetected = null;
    }
}

export default SpeechRecognizer;
