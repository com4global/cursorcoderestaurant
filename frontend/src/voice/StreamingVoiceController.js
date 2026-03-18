/**
 * StreamingVoiceController.js — WebSocket-based real-time voice controller
 * 
 * Replaces browser STT/TTS with server-side Sarvam streaming:
 * 1. Captures mic audio as PCM chunks via AudioWorklet
 * 2. Sends chunks to /ws/voice WebSocket
 * 3. Receives transcripts + TTS audio chunks
 * 4. Plays audio via AudioContext queue
 * 5. Supports barge-in (interrupt AI mid-sentence)
 */

import { useState, useRef, useCallback, useEffect } from 'react';

const STATES = { IDLE: 'idle', LISTENING: 'listening', PROCESSING: 'processing', SPEAKING: 'speaking' };
const SILENCE_TIMEOUT_MS = 1200; // 1.2s silence → process

/**
 * useStreamingVoice — real-time voice hook via WebSocket
 * 
 * @param {object} config
 * @param {string} config.wsUrl - WebSocket URL (e.g. "ws://localhost:8000/ws/voice")
 * @param {string} config.token - Auth token
 * @param {number|null} config.sessionId - Chat session ID
 * @param {number|null} config.restaurantId - Selected restaurant ID
 * @param {function} config.onTranscript - (text, isFinal) => void
 * @param {function} config.onResponse - (data) => void — {text, categories, items, session_id}
 * @param {function} config.onStateChange - (state) => void
 */
export function useStreamingVoice({
    wsUrl,
    token,
    sessionId,
    restaurantId,
    onTranscript,
    onResponse,
    onStateChange,
}) {
    const [voiceMode, setVoiceMode] = useState(false);
    const [voiceState, setVoiceState] = useState(STATES.IDLE);
    const [liveTranscript, setLiveTranscript] = useState('');
    const [isListening, setIsListening] = useState(false);

    const voiceModeRef = useRef(false);
    const wsRef = useRef(null);
    const micStreamRef = useRef(null);
    const mediaRecorderRef = useRef(null);
    const audioContextRef = useRef(null);
    const audioQueueRef = useRef([]);
    const isPlayingRef = useRef(false);
    const silenceTimerRef = useRef(null);
    const hasAudioRef = useRef(false);

    // Update external state
    useEffect(() => {
        onStateChange?.(voiceState);
    }, [voiceState, onStateChange]);

    // ---- Audio Playback Queue ----
    const playNextChunk = useCallback(() => {
        if (audioQueueRef.current.length === 0) {
            isPlayingRef.current = false;
            // Done speaking → start listening
            if (voiceModeRef.current) {
                updateState(STATES.LISTENING);
                startRecording();
            }
            return;
        }

        isPlayingRef.current = true;
        const audioData = audioQueueRef.current.shift();
        const blob = new Blob([audioData], { type: 'audio/wav' });
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);

        audio.onended = () => {
            URL.revokeObjectURL(url);
            playNextChunk();
        };
        audio.onerror = () => {
            URL.revokeObjectURL(url);
            playNextChunk();
        };
        audio.play().catch(() => playNextChunk());
    }, []);

    const updateState = useCallback((state) => {
        setVoiceState(state);
        if (state === STATES.LISTENING) setIsListening(true);
        else if (state === STATES.PROCESSING || state === STATES.SPEAKING) setIsListening(false);
    }, []);

    // ---- Barge-in: stop playback ----
    const bargeIn = useCallback(() => {
        audioQueueRef.current = [];
        isPlayingRef.current = false;
        // Send interrupt to server
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: 'interrupt' }));
        }
        console.log('%c[StreamVoice] ⚡ Barge-in', 'color: #ff6600; font-weight: bold');
    }, []);

    // ---- Silence Detection ----
    const resetSilenceTimer = useCallback(() => {
        if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
        silenceTimerRef.current = setTimeout(() => {
            if (hasAudioRef.current && wsRef.current?.readyState === WebSocket.OPEN) {
                console.log('%c[StreamVoice] 🔇 Silence detected → processing', 'color: #ffaa00');
                wsRef.current.send(JSON.stringify({ type: 'silence' }));
                updateState(STATES.PROCESSING);
                hasAudioRef.current = false;
                stopRecording();
            }
        }, SILENCE_TIMEOUT_MS);
    }, [updateState]);

    // ---- Mic Recording ----
    const startRecording = useCallback(async () => {
        if (!voiceModeRef.current) return;

        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                    sampleRate: 16000,
                },
            });
            micStreamRef.current = stream;

            // Use MediaRecorder to capture audio chunks
            const recorder = new MediaRecorder(stream, {
                mimeType: MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
                    ? 'audio/webm;codecs=opus'
                    : 'audio/webm',
            });

            recorder.ondataavailable = (event) => {
                if (event.data.size > 0 && wsRef.current?.readyState === WebSocket.OPEN) {
                    wsRef.current.send(event.data);
                    hasAudioRef.current = true;
                    resetSilenceTimer();
                }
            };

            recorder.start(200); // Send chunk every 200ms
            mediaRecorderRef.current = recorder;
            updateState(STATES.LISTENING);
            console.log('%c[StreamVoice] 🎤 Recording started', 'color: #00ff88');
        } catch (err) {
            console.error('[StreamVoice] Mic error:', err);
        }
    }, [resetSilenceTimer, updateState]);

    const stopRecording = useCallback(() => {
        if (mediaRecorderRef.current?.state === 'recording') {
            mediaRecorderRef.current.stop();
        }
        if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
    }, []);

    // ---- WebSocket Connection ----
    const connectWS = useCallback(() => {
        if (wsRef.current) {
            wsRef.current.close();
        }

        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
            console.log('%c[StreamVoice] 🔌 WebSocket connected', 'color: #00ff88; font-weight: bold');
            // Send config
            ws.send(JSON.stringify({
                type: 'config',
                token: token,
                session_id: sessionId,
                restaurant_id: restaurantId,
            }));
        };

        ws.onmessage = (event) => {
            if (event.data instanceof Blob) {
                // Binary = TTS audio chunk
                event.data.arrayBuffer().then(buffer => {
                    audioQueueRef.current.push(buffer);
                    if (!isPlayingRef.current) {
                        updateState(STATES.SPEAKING);
                        playNextChunk();
                    }
                });
                return;
            }

            // Text = JSON message
            try {
                const msg = JSON.parse(event.data);

                switch (msg.type) {
                    case 'ready':
                        console.log('%c[StreamVoice] ✅ Server ready', 'color: #00ff88');
                        startRecording();
                        break;

                    case 'transcript':
                        setLiveTranscript(msg.text || '');
                        onTranscript?.(msg.text, msg.final);
                        if (msg.final) {
                            console.log(`%c[StreamVoice] 📝 "${msg.text}"`, 'color: #00bbff; font-weight: bold');
                            updateState(STATES.PROCESSING);
                        }
                        break;

                    case 'response':
                        console.log(`%c[StreamVoice] 💬 "${(msg.text || '').substring(0, 60)}..."`, 'color: #bb88ff; font-weight: bold');
                        onResponse?.({
                            text: msg.text,
                            session_id: msg.session_id,
                            categories: msg.categories,
                            items: msg.items,
                            cart_summary: msg.cart_summary,
                        });
                        break;

                    case 'tts_start':
                        updateState(STATES.SPEAKING);
                        stopRecording();
                        break;

                    case 'tts_end':
                        // Playback continues from queue
                        if (audioQueueRef.current.length === 0 && !isPlayingRef.current) {
                            updateState(STATES.LISTENING);
                            startRecording();
                        }
                        break;

                    case 'interrupted':
                        console.log('%c[StreamVoice] ✂️ Interrupted', 'color: #ff6600');
                        updateState(STATES.LISTENING);
                        startRecording();
                        break;

                    case 'listening':
                        // Server acknowledges audio buffer
                        break;

                    case 'error':
                        console.error('[StreamVoice] Server error:', msg.message);
                        break;
                }
            } catch (e) {
                console.error('[StreamVoice] Parse error:', e);
            }
        };

        ws.onerror = (err) => {
            console.error('[StreamVoice] WS error:', err);
        };

        ws.onclose = (event) => {
            console.log(`%c[StreamVoice] 🔌 Disconnected (${event.code})`, 'color: #888');
            // Auto-reconnect if still in voice mode
            if (voiceModeRef.current) {
                setTimeout(() => {
                    if (voiceModeRef.current) connectWS();
                }, 2000);
            }
        };
    }, [wsUrl, token, sessionId, restaurantId, startRecording, stopRecording, playNextChunk, updateState, onTranscript, onResponse]);

    // ---- Toggle Voice Mode ----
    const toggleVoiceMode = useCallback(async () => {
        if (voiceMode) {
            // === TURN OFF ===
            voiceModeRef.current = false;
            setVoiceMode(false);
            updateState(STATES.IDLE);
            setLiveTranscript('');
            setIsListening(false);
            stopRecording();
            bargeIn();
            if (micStreamRef.current) {
                micStreamRef.current.getTracks().forEach(t => t.stop());
                micStreamRef.current = null;
            }
            if (wsRef.current) {
                wsRef.current.close();
                wsRef.current = null;
            }
        } else {
            // === TURN ON ===
            try {
                // Pre-check mic
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                stream.getTracks().forEach(t => t.stop());
            } catch (err) {
                console.error('[StreamVoice] Mic not available:', err);
                return;
            }

            voiceModeRef.current = true;
            setVoiceMode(true);
            updateState(STATES.LISTENING);
            connectWS();
        }
    }, [voiceMode, connectWS, stopRecording, bargeIn, updateState]);

    // Cleanup on unmount
    useEffect(() => {
        return () => {
            voiceModeRef.current = false;
            stopRecording();
            if (micStreamRef.current) {
                micStreamRef.current.getTracks().forEach(t => t.stop());
            }
            if (wsRef.current) {
                wsRef.current.close();
            }
        };
    }, [stopRecording]);

    return {
        voiceMode,
        voiceState,
        liveTranscript,
        isListening,
        toggleVoiceMode,
        bargeIn,
        // Expose speak for fallback (uses native TTS like before)
        speak: useCallback((text) => {
            if (!voiceModeRef.current || !text) return;
            // Use native TTS as quick fallback
            window.speechSynthesis?.cancel();
            const cleanText = text
                .replace(/\*\*|__|~~|`/g, '')
                .replace(/#{1,6}\s*/g, '')
                .replace(/[🎤🍽️😊👋🔥📦⚠️⏳🌶️🍕🍔🍟🍣🍛🍰☕🍺🥤💧🍳🥞🧀🫔🧃🍵🍷🍸🍩🍪🍨🥧🍫🍎🍄🌽🍅✨🎙️🔊✕•🛒]/g, '')
                .replace(/\n+/g, '. ')
                .replace(/\s+/g, ' ')
                .trim();
            if (!cleanText) return;
            const utterance = new SpeechSynthesisUtterance(cleanText);
            utterance.rate = 1.15;
            utterance.onend = () => {
                if (voiceModeRef.current) {
                    updateState(STATES.LISTENING);
                    startRecording();
                }
            };
            updateState(STATES.SPEAKING);
            window.speechSynthesis.speak(utterance);
        }, [updateState, startRecording]),
    };
}

export default useStreamingVoice;
