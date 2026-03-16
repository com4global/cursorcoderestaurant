/**
 * useVoiceController.js — React hook for ultra-low latency voice AI
 *
 * Orchestrates: SpeechRecognizer → IntentParser → Chat API → TTSPlayer
 *
 * Features:
 * - Continuous speech recognition with live transcript
 * - Fast intent parsing (<10ms) before backend hit
 * - Streaming text display (word-by-word reveal)
 * - Sentence-chunked TTS via AudioContext (iOS-safe)
 * - Barge-in (user interrupts → TTS stops, listening resumes)
 * - Voice state machine: IDLE → LISTENING → PROCESSING → SPEAKING
 * - iOS: AudioContext priming, single-shot STT, MediaRecorder fallback for WKWebView
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import { SpeechRecognizer } from './SpeechRecognizer.js';
import { TTSPlayer } from './TTSPlayer.js';
import { parseIntent } from './IntentParser.js';
import { trace, traceError } from './trace.js';
import { vlog } from './VoiceDebugLogger.js';

const STATES = { IDLE: 'idle', LISTENING: 'listening', PROCESSING: 'processing', SPEAKING: 'speaking' };

const _isIOS = typeof navigator !== 'undefined' && /iPad|iPhone|iPod/.test(navigator.userAgent);

/**
 * Streaming text reveal — reveals text word-by-word
 */
function streamTextToCallback(text, callback, intervalMs = 25) {
    const words = text.split(/\s+/);
    let current = '';
    let i = 0;
    const timer = setInterval(() => {
        if (i >= words.length) {
            clearInterval(timer);
            callback(text);
            return;
        }
        current = current ? current + ' ' + words[i] : words[i];
        callback(current);
        i++;
    }, intervalMs);
    return () => clearInterval(timer);
}

/**
 * useVoiceController hook
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
    useEffect(() => { voiceStateRef.current = voiceState; }, [voiceState]);

    const ttsLang = language === 'ta' ? 'ta-IN' : 'en-IN';

    // Initialize components — pass apiBase to SpeechRecognizer for MediaRecorder fallback
    useEffect(() => {
        recognizerRef.current = new SpeechRecognizer({ lang: ttsLang, apiBase });
        ttsPlayerRef.current = new TTSPlayer(apiBase);

        return () => {
            recognizerRef.current?.destroy();
            ttsPlayerRef.current?.destroy();
        };
    }, [apiBase]);

    useEffect(() => {
        if (recognizerRef.current) recognizerRef.current.setLang(language === 'ta' ? 'ta-IN' : 'en-IN');
    }, [language]);

    // Barge-in: stop TTS when user speaks
    const bargeIn = useCallback(() => {
        if (ttsPlayerRef.current?.isPlaying) {
            ttsPlayerRef.current.stop();
            vlog('STATE', 'Barge-in: TTS stopped');
        }
        if (streamCancelRef.current) {
            streamCancelRef.current();
            streamCancelRef.current = null;
        }
        setVoiceState(STATES.LISTENING);
    }, []);

    // Process finalized speech
    const handleFinalTranscript = useCallback(async (text, confidence = 0) => {
        if (!text.trim() || !voiceModeRef.current) return;

        const confStr = confidence > 0 ? (confidence * 100).toFixed(0) + '%' : 'N/A';
        trace('voice.finalTranscript', { text, confidence: confStr });
        vlog('STT', `Final: "${text}" (${confStr})`);

        setVoiceState(STATES.PROCESSING);
        setLiveTranscript('');
        setVoiceTranscript(text);

        if (doSendRef?.current) {
            vlog('STATE', `→ doSend: "${text.substring(0, 50)}"`);
            try {
                await doSendRef.current(text, true, confidence);
                vlog('STATE', 'doSend completed');
            } catch (err) {
                traceError('voice.doSendError', err, { text: text.substring(0, 60) });
                vlog('ERR', `doSend error: ${err.message}`);
            }
        }
    }, [doSendRef]);

    // Start listening
    const startListening = useCallback(() => {
        if (!voiceModeRef.current) return;
        const recognizer = recognizerRef.current;
        if (!recognizer) return;

        vlog('STT', 'startListening()', { iOS: _isIOS });

        recognizer.setLang(languageRef.current === 'ta' ? 'ta-IN' : 'en-IN');

        recognizer.onLiveTranscript = (text) => {
            setLiveTranscript(text);
            setIsListening(true);
        };
        recognizer.onFinalTranscript = handleFinalTranscript;
        recognizer.onStateChange = (state) => {
            vlog('STATE', `STT → ${state}`);
            if (state === 'listening') {
                setVoiceState(STATES.LISTENING);
                setIsListening(true);
            } else if (state === 'idle') {
                setIsListening(false);
            }
        };
        recognizer.onSpeechDetected = () => {
            if (voiceStateRef.current === STATES.SPEAKING) bargeIn();
        };
        recognizer.onError = (err) => {
            vlog('ERR', `STT error: ${err}`);
            setVoiceTranscript('⚠️ ' + err);
            setTimeout(() => setVoiceTranscript(''), 4000);
        };

        recognizer.start();
    }, [handleFinalTranscript, bargeIn]);

    // Speak via TTS — with guaranteed restart of STT after
    const speak = useCallback((text) => {
        if (!voiceModeRef.current || !text) return;

        ttsPlayerRef.current?.stop();
        vlog('TTS', `speak(): "${(text || '').substring(0, 60)}"`);
        setVoiceState(STATES.SPEAKING);

        const player = ttsPlayerRef.current;

        // CRITICAL: Always restart listening after TTS completes OR fails.
        // This prevents the cycle from getting stuck.
        const restartListening = () => {
            if (voiceModeRef.current) {
                vlog('STATE', 'TTS done → restarting STT');
                setVoiceState(STATES.LISTENING);
                startListening();
            }
        };

        player.onComplete = restartListening;
        player.onStateChange = (state) => {
            vlog('STATE', `TTS → ${state}`);
            if (state === 'speaking') setVoiceState(STATES.SPEAKING);
        };

        const lang = languageRef.current === 'ta' ? 'ta-IN' : 'en-IN';
        player.speak(text, { lang }).catch((err) => {
            vlog('ERR', `TTS speak error: ${err.message}`);
            restartListening(); // Always restart even on failure
        });
    }, [startListening]);

    // Toggle voice mode
    const toggleVoiceMode = useCallback(async () => {
        if (voiceMode) {
            // === OFF ===
            vlog('STATE', 'Voice OFF');
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
            // === ON ===
            vlog('STATE', 'Voice ON', { iOS: _isIOS });

            // DIAGNOSTIC ALERTS — will remove after debugging
            const diag = (location.search || '').includes('voicedebug');
            if (diag) alert('Step 1: Voice ON. iOS=' + _isIOS);

            // CRITICAL: Prime AudioContext during this user gesture (tap)
            // This is the ONE chance to unlock audio on iOS
            ttsPlayerRef.current?.primeForIOS();
            if (diag) alert('Step 2: AudioContext primed');

            voiceModeRef.current = true;
            setVoiceMode(true);
            setVoiceState(STATES.LISTENING);

            // Request mic permission first, then greet + listen
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                stream.getTracks().forEach(t => t.stop());
                vlog('MIC', 'Mic permission granted');
                if (diag) alert('Step 3: Mic permission GRANTED');
            } catch (err) {
                vlog('ERR', `Mic permission: ${err.name} ${err.message}`);
                if (diag) alert('Step 3: Mic FAILED: ' + err.name + ' ' + err.message);
                if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
                    setVoiceTranscript('⚠️ Microphone blocked — enable in settings');
                } else if (err.name === 'NotFoundError') {
                    setVoiceTranscript('⚠️ No microphone found');
                } else {
                    setVoiceTranscript('⚠️ Mic error: ' + (err.message || err.name));
                }
                setTimeout(() => setVoiceTranscript(''), 4000);
                return; // Don't start if mic denied
            }

            // Speak greeting (TTS will call restartListening when done)
            if (diag) alert('Step 4: About to speak greeting');
            const greet = languageRef.current === 'ta'
                ? "வணக்கம்! நீங்கள் என்ன சாப்பிட விரும்புகிறீர்கள்?"
                : "Hello! What would you like to eat?";
            speak(greet);
            if (diag) alert('Step 5: speak() called. TTS should play then STT starts.');
        }
    }, [voiceMode, speak]);

    return {
        voiceMode,
        voiceState,
        setVoiceState,
        liveTranscript,
        voiceTranscript,
        isListening,

        voiceModeRef,
        voiceStateRef,

        toggleVoiceMode,
        speak,
        bargeIn,
        startListening,

        streamText: (text, callback) => {
            if (streamCancelRef.current) streamCancelRef.current();
            streamCancelRef.current = streamTextToCallback(text, callback);
        },
    };
}

export default useVoiceController;
