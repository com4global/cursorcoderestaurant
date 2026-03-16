/**
 * useVoiceController.js — React hook for ultra-low latency voice AI
 * 
 * Orchestrates: SpeechRecognizer → IntentParser → Chat API → TTSPlayer
 * 
 * Features:
 * - Continuous speech recognition with live transcript
 * - Fast intent parsing (<10ms) before backend
 * - Streaming text display (word-by-word reveal)
 * - Sentence-chunked TTS (plays first sentence while generating rest)
 * - Barge-in (user interrupts → TTS stops, listening resumes)
 * - Voice state machine: IDLE → LISTENING → PROCESSING → SPEAKING
 * - iOS compatibility: proper audio priming, single-shot STT, controlled restart
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import { SpeechRecognizer } from './SpeechRecognizer.js';
import { TTSPlayer } from './TTSPlayer.js';
import { parseIntent } from './IntentParser.js';
import { trace, traceError } from './trace.js';
import { vlog } from './VoiceDebugLogger.js';

// Voice states
const STATES = { IDLE: 'idle', LISTENING: 'listening', PROCESSING: 'processing', SPEAKING: 'speaking' };

const _isIOS = typeof navigator !== 'undefined' && /iPad|iPhone|iPod/.test(navigator.userAgent);

/**
 * Streaming text reveal — reveals text word-by-word for perceived speed
 */
function streamTextToCallback(text, callback, intervalMs = 25) {
    const words = text.split(/\s+/);
    let current = '';
    let i = 0;
    const timer = setInterval(() => {
        if (i >= words.length) {
            clearInterval(timer);
            callback(text); // Ensure full text is shown
            return;
        }
        current = current ? current + ' ' + words[i] : words[i];
        callback(current);
        i++;
    }, intervalMs);
    return () => clearInterval(timer); // Return cancel function
}

/**
 * useVoiceController hook — plug into any React component
 * 
 * @param {object} config
 * @param {string} config.apiBase - Backend API URL (e.g. "http://localhost:8000")
 * @param {function} config.onSendMessage - (text, fromVoice) => void — send message to chat
 * @param {function} config.onAddBotMessage - (text) => void — add bot message to chat
 * @param {function} config.doSendRef - ref to doSend function
 * @param {string} config.language - 'en' | 'ta' for English or Tamil (STT + TTS)
 * @returns Voice state and control functions
 */
export function useVoiceController({ apiBase, doSendRef, language = 'en' }) {
    const [voiceMode, setVoiceMode] = useState(false);
    const [voiceState, setVoiceState] = useState(STATES.IDLE);
    const [liveTranscript, setLiveTranscript] = useState('');
    const [voiceTranscript, setVoiceTranscript] = useState('');
    const [isListening, setIsListening] = useState(false);

    const voiceModeRef = useRef(false);
    const voiceStateRef = useRef(STATES.IDLE);
    const languageRef = useRef(language);
    const recognizerRef = useRef(null);
    const ttsPlayerRef = useRef(null);
    const streamCancelRef = useRef(null);

    useEffect(() => { languageRef.current = language; }, [language]);
    // Keep refs in sync
    useEffect(() => { voiceStateRef.current = voiceState; }, [voiceState]);

    const ttsLang = language === 'ta' ? 'ta-IN' : 'en-IN';

    // Initialize components
    useEffect(() => {
        recognizerRef.current = new SpeechRecognizer({ lang: ttsLang });
        ttsPlayerRef.current = new TTSPlayer(apiBase);

        return () => {
            recognizerRef.current?.destroy();
            ttsPlayerRef.current?.destroy();
        };
    }, [apiBase]);

    useEffect(() => {
        if (recognizerRef.current) recognizerRef.current.setLang(language === 'ta' ? 'ta-IN' : 'en-IN');
    }, [language]);

    // ---- Barge-in: stop TTS when user speaks ----
    const bargeIn = useCallback(() => {
        if (ttsPlayerRef.current?.isPlaying) {
            ttsPlayerRef.current.stop();
            vlog('STATE', 'Barge-in: TTS stopped by user speech');
        }
        if (streamCancelRef.current) {
            streamCancelRef.current();
            streamCancelRef.current = null;
        }
        setVoiceState(STATES.LISTENING);
    }, []);

    // ---- Process finalized speech ----
    const handleFinalTranscript = useCallback(async (text, confidence = 0) => {
        if (!text.trim() || !voiceModeRef.current) return;

        const confStr = confidence > 0 ? (confidence * 100).toFixed(0) + '%' : 'N/A';
        trace('voice.finalTranscript', { text, confidence: confStr });
        vlog('STT', `Final transcript: "${text}" (${confStr})`);
        console.log(`%c[Voice] 🎤 Final transcript: "${text}" (confidence: ${confStr})`, 'color: #00ff88; font-weight: bold; font-size: 13px');

        setVoiceState(STATES.PROCESSING);
        setLiveTranscript('');
        setVoiceTranscript(text);

        // Send to chat engine via doSend (handles all intents, cart, ordering)
        if (doSendRef?.current) {
            vlog('STATE', `Sending to doSend: "${text.substring(0, 50)}"`);
            try {
                await doSendRef.current(text, true, confidence);
                trace('voice.doSendComplete', { text: text.substring(0, 60) });
                vlog('STATE', 'doSend completed');
            } catch (err) {
                traceError('voice.doSendError', err, { text: text.substring(0, 60) });
                vlog('ERR', `doSend error: ${err.message}`);
            }
        } else {
            vlog('ERR', 'doSendRef.current is null');
        }
    }, [doSendRef]);

    // ---- Start listening ----
    const startListening = useCallback(() => {
        if (!voiceModeRef.current) return;
        const recognizer = recognizerRef.current;
        if (!recognizer) return;

        vlog('STT', 'startListening() called', { iOS: _isIOS });

        recognizer.setLang(languageRef.current === 'ta' ? 'ta-IN' : 'en-IN');

        recognizer.onLiveTranscript = (text) => {
            setLiveTranscript(text);
            setIsListening(true);
            if (!recognizer._lastLogTime || Date.now() - recognizer._lastLogTime > 500) {
                console.log('%c[Voice] 🔊 Hearing: "' + text + '"', 'color: #888');
                recognizer._lastLogTime = Date.now();
            }
        };
        recognizer.onFinalTranscript = handleFinalTranscript;
        recognizer.onStateChange = (state) => {
            vlog('STATE', `STT state → ${state}`);
            if (state === 'listening') {
                setVoiceState(STATES.LISTENING);
                setIsListening(true);
            } else if (state === 'idle') {
                setIsListening(false);
            }
        };
        recognizer.onSpeechDetected = () => {
            // Barge-in: if TTS is playing and user speaks, stop it
            if (voiceStateRef.current === STATES.SPEAKING) {
                bargeIn();
            }
        };
        recognizer.onError = (err) => {
            vlog('ERR', `STT error: ${err}`);
            setVoiceTranscript('⚠️ ' + err);
            setTimeout(() => setVoiceTranscript(''), 4000);
        };

        recognizer.start();
    }, [handleFinalTranscript, bargeIn]);

    // ---- Speak via Sarvam AI TTS ----
    const speak = useCallback((text) => {
        if (!voiceModeRef.current || !text) return;

        // Cancel any ongoing speech
        ttsPlayerRef.current?.stop();

        vlog('TTS', `speak() called: "${(text || '').substring(0, 60)}"`);

        setVoiceState(STATES.SPEAKING);

        // Wire up TTSPlayer callbacks for this utterance
        const player = ttsPlayerRef.current;
        player.onComplete = () => {
            vlog('STATE', 'TTS onComplete → restarting STT');
            if (voiceModeRef.current) {
                setVoiceState(STATES.LISTENING);
                // Always restart listening after TTS completes
                // On iOS: SpeechRecognizer now handles single-shot mode properly
                startListening();
            }
        };
        player.onStateChange = (state) => {
            vlog('STATE', `TTS state → ${state}`);
            if (state === 'speaking') setVoiceState(STATES.SPEAKING);
            else if (state === 'idle' && voiceModeRef.current) setVoiceState(STATES.LISTENING);
        };

        const lang = languageRef.current === 'ta' ? 'ta-IN' : 'en-IN';
        player.speak(text, { lang }).catch((err) => {
            vlog('ERR', `TTS speak error: ${err.message}`);
            if (voiceModeRef.current) {
                setVoiceState(STATES.LISTENING);
                startListening();
            }
        });
    }, [startListening]);

    // ---- Toggle voice mode ----
    const toggleVoiceMode = useCallback(async () => {
        if (voiceMode) {
            // === TURN OFF ===
            vlog('STATE', 'Voice mode OFF');
            voiceModeRef.current = false;
            setVoiceMode(false);
            setVoiceState(STATES.IDLE);
            setVoiceTranscript('');
            setLiveTranscript('');
            setIsListening(false);
            recognizerRef.current?.stop();
            ttsPlayerRef.current?.stop();
            if (streamCancelRef.current) { streamCancelRef.current(); streamCancelRef.current = null; }
        } else {
            // === TURN ON ===
            vlog('STATE', 'Voice mode ON', { iOS: _isIOS });

            // iOS: prime the TTS audio element IN THIS USER GESTURE
            // This must happen synchronously in the tap handler
            if (_isIOS) {
                ttsPlayerRef.current?.primeForIOS();
            }

            voiceModeRef.current = true;
            setVoiceMode(true);
            setVoiceState(STATES.LISTENING);

            // Start recognition synchronously (required on iOS)
            startListening();

            // Request mic permission and play greeting after
            navigator.mediaDevices.getUserMedia({ audio: true })
                .then((stream) => {
                    stream.getTracks().forEach(t => t.stop());
                    vlog('MIC', 'Microphone permission granted');
                    const greet = languageRef.current === 'ta'
                        ? "வணக்கம்! நீங்கள் என்ன சாப்பிட விரும்புகிறீர்கள்?"
                        : "Hello! What would you like to eat?";
                    speak(greet);
                })
                .catch((err) => {
                    vlog('ERR', `Mic permission error: ${err.name} ${err.message}`);
                    if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
                        setVoiceTranscript('⚠️ Microphone blocked — enable in browser settings');
                    } else if (err.name === 'NotFoundError') {
                        setVoiceTranscript('⚠️ No microphone found');
                    } else {
                        setVoiceTranscript('⚠️ Mic error: ' + (err.message || err.name));
                    }
                    setTimeout(() => setVoiceTranscript(''), 4000);
                });
        }
    }, [voiceMode, startListening, speak]);

    return {
        // State
        voiceMode,
        voiceState,
        setVoiceState,
        liveTranscript,
        voiceTranscript,
        isListening,

        // Refs (for App.jsx compatibility)
        voiceModeRef,
        voiceStateRef,

        // Controls
        toggleVoiceMode,
        speak,          // Manually trigger TTS
        bargeIn,        // Stop TTS
        startListening, // Manually start STT

        // For streaming text display
        streamText: (text, callback) => {
            if (streamCancelRef.current) streamCancelRef.current();
            streamCancelRef.current = streamTextToCallback(text, callback);
        },
    };
}

export default useVoiceController;
