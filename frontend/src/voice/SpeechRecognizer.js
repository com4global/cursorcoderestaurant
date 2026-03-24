/**
 * SpeechRecognizer.js — Browser speech recognition with iOS + WKWebView fallback
 *
 * Strategy:
 * - Desktop Chrome/Safari: Native webkitSpeechRecognition (continuous=true)
 * - iOS Safari/Chrome: Native webkitSpeechRecognition (continuous=false, single-shot)
 * - WKWebView (Tauri iOS app): SpeechRecognition doesn't exist → fallback to
 *   MediaRecorder + backend /api/voice/stt (Sarvam Saaras STT)
 *
 * iOS improvements:
 * - Voice Activity Detection (VAD) using AudioContext analyser
 * - Auto-stop when silence detected (faster response)
 * - Correct MIME type (audio/mp4 on iOS, audio/webm on Chrome)
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
        this._receivedFinalTranscript = false;
        this._useFallback = false;
        this._mediaRecorder = null;
        this._audioChunks = [];
        this._mediaStream = null;
        this._recorderTimeout = null;
        this._vadInterval = null;

        // Callbacks
        this.onLiveTranscript = null;
        this.onFinalTranscript = null;
        this.onStateChange = null;
        this.onError = null;
        this.onSpeechDetected = null;
        this.onStoppedWithoutTranscript = null;
    }

    static isSupported() {
        if (window.SpeechRecognition || window.webkitSpeechRecognition) return true;
        if (navigator.mediaDevices && typeof MediaRecorder !== 'undefined') return true;
        return false;
    }

    start() {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SR) {
            this._useFallback = false;
            return this._startNative(SR);
        }
        if (navigator.mediaDevices && typeof MediaRecorder !== 'undefined') {
            vlog('IOS', 'No SpeechRecognition API — using MediaRecorder fallback');
            this._useFallback = true;
            return this._startMediaRecorder();
        }
        vlog('ERR', 'No speech recognition available');
        this.onError?.('Speech recognition not supported in this browser');
        return false;
    }

    _startNative(SR) {
        this.stop();
        this.finalTranscript = '';
        this._intentionallyStopped = false;
        this._receivedFinalTranscript = false;

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

            if (final) this.finalTranscript = (this.finalTranscript + ' ' + final).trim();
            if (confidenceCount > 0) this._lastConfidence = confidenceSum / confidenceCount;
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
                this._receivedFinalTranscript = true;
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
                    this._receivedFinalTranscript = true;
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

            if (this._intentionallyStopped && !this._receivedFinalTranscript) {
                this.onStoppedWithoutTranscript?.();
            }

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
     * MediaRecorder fallback with Voice Activity Detection (VAD)
     * - Uses AudioContext analyser to detect speech vs silence
     * - Auto-stops when 1.5s of silence detected AFTER speech started
     * - Max recording time: 8s (safety cap)
     * - Min recording time: 1s (avoid false triggers)
     */
    async _startMediaRecorder() {
        this.stop();
        this._intentionallyStopped = false;
        this._receivedFinalTranscript = false;
        this._audioChunks = [];

        try {
            // Get mic stream
            if (!this._mediaStream || this._mediaStream.getTracks().every(t => t.readyState === 'ended')) {
                this._mediaStream = await navigator.mediaDevices.getUserMedia({
                    audio: {
                        echoCancellation: true,
                        noiseSuppression: true,
                        autoGainControl: true,
                        sampleRate: 16000,
                    }
                });
                vlog('MIC', 'MediaRecorder: mic stream acquired');
            }

            // Pick best MIME type — iOS prefers mp4
            let mimeType = 'audio/webm';
            if (typeof MediaRecorder.isTypeSupported === 'function') {
                // IMPORTANT: Check mp4 FIRST on iOS (native codec, better quality)
                if (_isIOS && MediaRecorder.isTypeSupported('audio/mp4')) {
                    mimeType = 'audio/mp4';
                } else if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
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

            // Set up VAD (Voice Activity Detection) using AudioContext
            let speechDetected = false;
            let silenceStart = null;
            const SILENCE_THRESHOLD = 15;    // RMS threshold for "silence"
            const SILENCE_DURATION = 1500;   // ms of silence after speech to auto-stop
            const MIN_RECORDING = 1000;      // minimum ms before allowing auto-stop
            const MAX_RECORDING = 8000;      // maximum recording duration
            const recordStart = Date.now();

            try {
                const ac = new (window.AudioContext || window.webkitAudioContext)();
                const source = ac.createMediaStreamSource(this._mediaStream);
                const analyser = ac.createAnalyser();
                analyser.fftSize = 512;
                source.connect(analyser);
                const dataArray = new Uint8Array(analyser.frequencyBinCount);

                this._vadInterval = setInterval(() => {
                    if (recorder.state !== 'recording') {
                        clearInterval(this._vadInterval);
                        ac.close().catch(() => { });
                        return;
                    }

                    analyser.getByteFrequencyData(dataArray);
                    // Calculate RMS energy
                    let sum = 0;
                    for (let i = 0; i < dataArray.length; i++) sum += dataArray[i] * dataArray[i];
                    const rms = Math.sqrt(sum / dataArray.length);

                    const elapsed = Date.now() - recordStart;

                    if (rms > SILENCE_THRESHOLD) {
                        // Speech detected
                        if (!speechDetected) {
                            speechDetected = true;
                            vlog('VAD', `Speech detected (RMS=${rms.toFixed(0)})`);
                            this.onLiveTranscript?.('🎤 Speaking...');
                        }
                        silenceStart = null;
                    } else if (speechDetected && elapsed > MIN_RECORDING) {
                        // Silence after speech
                        if (!silenceStart) {
                            silenceStart = Date.now();
                        } else if (Date.now() - silenceStart > SILENCE_DURATION) {
                            // Enough silence — stop recording
                            vlog('VAD', `Silence detected for ${SILENCE_DURATION}ms — stopping`);
                            clearInterval(this._vadInterval);
                            ac.close().catch(() => { });
                            if (recorder.state === 'recording') recorder.stop();
                            return;
                        }
                    }

                    // Safety: max recording time
                    if (elapsed > MAX_RECORDING) {
                        vlog('VAD', 'Max recording time reached — stopping');
                        clearInterval(this._vadInterval);
                        ac.close().catch(() => { });
                        if (recorder.state === 'recording') recorder.stop();
                    }
                }, 100);  // Check every 100ms

            } catch (vadErr) {
                vlog('ERR', `VAD setup failed (non-fatal): ${vadErr.message}`);
                // Fall back to simple timeout if VAD fails
                this._recorderTimeout = setTimeout(() => {
                    if (recorder.state === 'recording') {
                        vlog('MIC', 'Auto-stopping MediaRecorder (fallback timeout)');
                        recorder.stop();
                    }
                }, 5000);
            }

            recorder.ondataavailable = (e) => {
                if (e.data.size > 0) this._audioChunks.push(e.data);
            };

            recorder.onstop = async () => {
                clearInterval(this._vadInterval);
                clearTimeout(this._recorderTimeout);

                if (this._intentionallyStopped || this._audioChunks.length === 0) {
                    vlog('MIC', 'MediaRecorder stopped (no data or intentional)');
                    if (!this._receivedFinalTranscript) {
                        this.onStoppedWithoutTranscript?.();
                    }
                    this.isListening = false;
                    this.onStateChange?.('idle');
                    return;
                }

                const fileExt = mimeType.includes('mp4') ? 'audio.mp4'
                    : mimeType.includes('wav') ? 'audio.wav'
                        : 'audio.webm';
                const blob = new Blob(this._audioChunks, { type: mimeType });
                this._audioChunks = [];

                vlog('MIC', `Sending ${(blob.size / 1024).toFixed(1)}KB (${fileExt}) to backend STT`);
                this.onLiveTranscript?.('⏳ Processing...');

                // Send to backend STT
                const formData = new FormData();
                formData.append('file', blob, fileExt);
                formData.append('language', this.lang || 'en-IN');

                try {
                    const resp = await fetch(`${this.apiBase}/api/voice/stt`, {
                        method: 'POST',
                        body: formData,
                    });
                    if (resp.ok) {
                        const data = await resp.json();
                        const transcript = (data.transcript || '').trim();
                        vlog('STT', `Backend STT: "${transcript}"`);
                        if (transcript) {
                            this._receivedFinalTranscript = true;
                            this.onLiveTranscript?.(transcript);
                            this.onFinalTranscript?.(transcript, 0.8);
                        } else {
                            vlog('STT', 'Empty transcript');
                            this.onStoppedWithoutTranscript?.();
                            this.onError?.("Didn't catch that — try speaking closer to mic");
                            this.onStateChange?.('idle');
                        }
                    } else {
                        const errText = await resp.text().catch(() => '');
                        vlog('ERR', `Backend STT ${resp.status}: ${errText.substring(0, 200)}`);
                        this.onError?.('Voice recognition error — please try again');
                        this.onStateChange?.('idle');
                    }
                } catch (err) {
                    vlog('ERR', `Backend STT network error: ${err.message}`);
                    this.onError?.('Network error — check connection');
                    this.onStateChange?.('idle');
                }

                this.isListening = false;
            };

            recorder.onerror = (e) => {
                vlog('ERR', `MediaRecorder error: ${e.error?.message || 'unknown'}`);
                this.isListening = false;
                this.onStateChange?.('idle');
            };

            // Start recording with 250ms timeslice (collects data periodically)
            recorder.start(250);
            this.isListening = true;
            this.onStateChange?.('listening');
            this.onLiveTranscript?.('🎤 Listening...');
            vlog('MIC', 'MediaRecorder started with VAD');

            return true;
        } catch (err) {
            vlog('ERR', `MediaRecorder start failed: ${err.message}`);
            this.onError?.('Mic error: ' + err.message);
            this.onStateChange?.('idle');
            return false;
        }
    }

    stopRecording() {
        clearInterval(this._vadInterval);
        if (this._mediaRecorder && this._mediaRecorder.state === 'recording') {
            clearTimeout(this._recorderTimeout);
            this._mediaRecorder.stop();
            vlog('MIC', 'MediaRecorder manually stopped');
        }
    }

    finish() {
        clearTimeout(this.debounceTimer);
        clearTimeout(this._recorderTimeout);
        clearInterval(this._vadInterval);
        this.isListening = false;
        this._intentionallyStopped = true;

        if (this.recognition) {
            try {
                if (typeof this.recognition.stop === 'function') {
                    this.recognition.stop();
                    vlog('STT', 'recognition.stop() called');
                } else {
                    this.recognition.abort();
                    this.recognition = null;
                }
            } catch {
                try { this.recognition.abort(); } catch { }
                this.recognition = null;
            }
            return;
        }

        if (this._mediaRecorder && this._mediaRecorder.state === 'recording') {
            this.stopRecording();
            return;
        }

        this.onStateChange?.('idle');
    }

    setLang(lang) {
        this.lang = (typeof lang === 'string' && lang === 'ta-IN') ? 'ta-IN' : 'en-IN';
    }

    stop() {
        clearTimeout(this.debounceTimer);
        clearTimeout(this._recorderTimeout);
        clearInterval(this._vadInterval);
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
        this.onStoppedWithoutTranscript = null;
    }
}

export default SpeechRecognizer;
