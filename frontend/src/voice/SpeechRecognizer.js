/**
 * SpeechRecognizer.js — Browser speech recognition with iOS compatibility
 * Features:
 * - continuous = true on desktop (never cuts off mid-sentence)
 * - continuous = false on iOS (only mode that works on WebKit)
 * - interimResults on desktop, disabled on iOS (reduces flakiness)
 * - Silence debounce on desktop (sends when user finishes)
 * - Auto-restart on errors (desktop only — iOS needs user gesture)
 * - Barge-in detection
 */

import { vlog } from './VoiceDebugLogger.js';

const DEBOUNCE_MS = 1000; // 1 second of silence before sending (fast response)

const _isIOS = typeof navigator !== 'undefined' && /iPad|iPhone|iPod/.test(navigator.userAgent);
const _isSafari = typeof navigator !== 'undefined' && /^((?!chrome|android).)*safari/i.test(navigator.userAgent);
const _isIOSWebKit = _isIOS || (_isSafari && 'ontouchend' in document);

export class SpeechRecognizer {
    constructor(options = {}) {
        this.recognition = null;
        this.debounceTimer = null;
        this.finalTranscript = '';
        this.isListening = false;
        this.lang = options.lang || 'en-IN';
        /** If true, do not stop after final transcript (iOS: restart requires user gesture) */
        this.keepListeningOnFinal = options.keepListeningOnFinal === true;
        this._intentionallyStopped = false;

        // Callbacks
        this.onLiveTranscript = null;  // (text) => void — live partial text
        this.onFinalTranscript = null; // (text) => void — debounced final text
        this.onStateChange = null;     // (state) => void — 'listening'|'idle'
        this.onError = null;           // (error) => void
        this.onSpeechDetected = null;  // () => void — for barge-in detection
    }

    /**
     * Check if SpeechRecognition API is available
     */
    static isSupported() {
        return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
    }

    /**
     * Start continuous listening
     */
    start() {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) {
            vlog('STT', 'SpeechRecognition NOT supported');
            this.onError?.('Speech recognition not supported in this browser');
            return false;
        }

        this.stop(); // Clean up any existing instance
        this.finalTranscript = '';
        this._intentionallyStopped = false;

        const recognition = new SR();

        // iOS WebKit: continuous=true silently breaks recognition.
        // Use single-shot mode on iOS, continuous on desktop.
        if (_isIOSWebKit) {
            recognition.continuous = false;
            recognition.interimResults = false; // iOS interim results are unreliable
            vlog('IOS', 'Using single-shot mode (continuous=false, interimResults=false)');
        } else {
            recognition.continuous = true;
            recognition.interimResults = true;
        }

        recognition.lang = this.lang;
        recognition.maxAlternatives = 1;
        this.recognition = recognition;

        recognition.onstart = () => {
            this.isListening = true;
            vlog('STT', 'recognition.onstart fired', { lang: this.lang, iOS: _isIOSWebKit });
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

            vlog('STT', 'onresult', { final: final || '(none)', interim: interim || '(none)', confidence: confidenceCount > 0 ? (confidenceSum / confidenceCount).toFixed(2) : 'N/A' });

            // Accumulate final results
            if (final) {
                this.finalTranscript = (this.finalTranscript + ' ' + final).trim();
            }

            // Track confidence (average across all final results)
            if (confidenceCount > 0) {
                this._lastConfidence = confidenceSum / confidenceCount;
            }

            // Persist latest interim text so debounce timer can access it
            this._lastInterim = interim;

            // Notify barge-in detection (any speech detected)
            this.onSpeechDetected?.();

            // Show live transcript
            const display = (this.finalTranscript + ' ' + interim).trim();
            this.onLiveTranscript?.(display);

            // iOS single-shot mode: we get one final result, send it immediately
            if (_isIOSWebKit && final) {
                const textToSend = this.finalTranscript.trim();
                const confidence = this._lastConfidence || 0;
                vlog('IOS', 'Single-shot final → sending', { text: textToSend, confidence: confidence.toFixed(2) });
                this.finalTranscript = '';
                this._lastInterim = '';
                this._lastConfidence = 0;
                this.onLiveTranscript?.('');
                // Don't stop — iOS will fire onend automatically
                this.onFinalTranscript?.(textToSend, confidence);
                return;
            }

            // Desktop: Reset debounce timer on every new result
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
            vlog('ERR', `recognition.onerror: ${e.error}`, { message: e.message || '' });

            if (e.error === 'no-speech') {
                // Auto-restart after no speech (desktop only)
                if (!_isIOSWebKit) {
                    setTimeout(() => this.start(), 500);
                } else {
                    vlog('IOS', 'no-speech error — NOT auto-restarting (needs gesture)');
                    this.onStateChange?.('idle');
                }
            } else if (e.error === 'aborted') {
                // Intentional, ignore
                vlog('STT', 'recognition aborted (intentional)');
            } else if (e.error === 'not-allowed') {
                this.onError?.('Microphone blocked — enable in browser settings');
                this.onStateChange?.('idle');
            } else {
                this.onError?.('Mic error: ' + e.error);
                // Try to restart (desktop only)
                if (!_isIOSWebKit) {
                    setTimeout(() => this.start(), 1000);
                } else {
                    this.onStateChange?.('idle');
                }
            }
        };

        recognition.onend = () => {
            this.isListening = false;
            vlog('STT', 'recognition.onend fired', { intentionallyStopped: this._intentionallyStopped, iOS: _isIOSWebKit });

            if (_isIOSWebKit) {
                // iOS: do NOT auto-restart. The controller will restart after TTS completes.
                this.onStateChange?.('idle');
                return;
            }

            // Desktop: Auto-restart if not intentionally stopped
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
            console.error('[SpeechRecognizer] Failed to start:', err);
            this.onStateChange?.('idle');
            return false;
        }
    }

    /**
     * Set language for next start (e.g. 'en-IN', 'ta-IN')
     */
    setLang(lang) {
        this.lang = lang || 'en-IN';
    }

    /**
     * Stop listening
     */
    stop() {
        clearTimeout(this.debounceTimer);
        this.isListening = false;
        this._intentionallyStopped = true;
        if (this.recognition) {
            try { this.recognition.abort(); } catch { }
            this.recognition = null;
        }
    }

    /**
     * Cleanup and destroy
     */
    destroy() {
        this.stop();
        this.onLiveTranscript = null;
        this.onFinalTranscript = null;
        this.onStateChange = null;
        this.onError = null;
        this.onSpeechDetected = null;
    }
}

export default SpeechRecognizer;
