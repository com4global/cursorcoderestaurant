/**
 * useVoiceController.js — React hook for voice AI
 *
 * Orchestrates: SpeechRecognizer → IntentParser → Chat API → TTSPlayer
 *
 * iOS improvements:
 * - AudioContext + Audio element priming during gesture
 * - STT starts immediately after greeting (doesn't wait for TTS completion)
 * - MediaRecorder fallback for WKWebView (auto-stop at 4s for faster response)
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import { SpeechRecognizer } from './SpeechRecognizer.js';
import { TTSPlayer } from './TTSPlayer.js';
import { parseIntent } from './IntentParser.js';
import { trace, traceError } from './trace.js';
import { vlog } from './VoiceDebugLogger.js';

const STATES = { IDLE: 'idle', LISTENING: 'listening', PROCESSING: 'processing', SPEAKING: 'speaking' };

const _isIOS = typeof navigator !== 'undefined' && /iPad|iPhone|iPod/.test(navigator.userAgent);

/** Normalize UI language to 'en' or 'ta'; default English so STT/TTS stay in sync with user selection. */
function normalizeVoiceLanguage(lang) {
    if (lang === 'ta' || (typeof lang === 'string' && lang.toLowerCase().startsWith('ta'))) return 'ta';
    return 'en';
}

/** Map to Sarvam/browser language code (en-IN or ta-IN only). */
function toLanguageCode(normalized) {
    return normalized === 'ta' ? 'ta-IN' : 'en-IN';
}

function streamTextToCallback(text, callback, intervalMs = 25) {
    const words = text.split(/\s+/);
    let current = '';
    let i = 0;
    const timer = setInterval(() => {
        if (i >= words.length) { clearInterval(timer); callback(text); return; }
        current = current ? current + ' ' + words[i] : words[i];
        callback(current);
        i++;
    }, intervalMs);
    return () => clearInterval(timer);
}

export function useVoiceController({
    apiBase,
    doSendRef,
    language = 'en',
    onTranscriptReady = null,
    onTranscriptInterim = null,
    onTranscriptCanceled = null,
}) {
    const [voiceMode, setVoiceMode] = useState(false);
    const [voiceState, setVoiceState] = useState(STATES.IDLE);
    const [liveTranscript, setLiveTranscript] = useState('');
    const [voiceTranscript, setVoiceTranscript] = useState('');
    const [isListening, setIsListening] = useState(false);

    const voiceModeRef = useRef(false);
    const voiceStateRef = useRef(STATES.IDLE);
    const normalizedLang = normalizeVoiceLanguage(language);
    const languageRef = useRef(normalizedLang);
    const recognizerRef = useRef(null);
    const ttsPlayerRef = useRef(null);
    const streamCancelRef = useRef(null);
    const startListeningRef = useRef(null); // stable ref for language-change restart
    const holdToTextModeRef = useRef(false);
    const heardSpeechRef = useRef(false);

    // Update languageRef synchronously every render — no async useEffect lag
    languageRef.current = normalizedLang;

    useEffect(() => { voiceStateRef.current = voiceState; }, [voiceState]);

    const langCode = toLanguageCode(normalizedLang);

    useEffect(() => {
        recognizerRef.current = new SpeechRecognizer({ lang: langCode, apiBase });
        ttsPlayerRef.current = new TTSPlayer(apiBase);
        return () => {
            recognizerRef.current?.destroy();
            ttsPlayerRef.current?.destroy();
        };
    }, [apiBase]);

    // When language changes while voice is active: update STT and restart if listening
    useEffect(() => {
        const code = toLanguageCode(normalizeVoiceLanguage(language));
        if (recognizerRef.current) recognizerRef.current.setLang(code);
        vlog('LANG', `Voice language: ${language} → ${code} (STT+TTS)`);

        // If currently listening in old language, restart recognition with new language
        if (voiceModeRef.current && voiceStateRef.current === STATES.LISTENING) {
            recognizerRef.current?.stop();
            setTimeout(() => {
                if (voiceModeRef.current) startListeningRef.current?.();
            }, 200);
        }
        // If TTS is playing in old language, stop it — next speak() will use new language
        if (voiceModeRef.current && ttsPlayerRef.current?.isPlaying) {
            ttsPlayerRef.current.stop();
        }
    }, [language]);

    const resetVoiceSession = useCallback(() => {
        holdToTextModeRef.current = false;
        heardSpeechRef.current = false;
        voiceModeRef.current = false;
        setVoiceMode(false);
        setVoiceState(STATES.IDLE);
        setLiveTranscript('');
        setVoiceTranscript('');
        setIsListening(false);
    }, []);

    const stopVoiceSession = useCallback(() => {
        voiceModeRef.current = false;
        recognizerRef.current?.stop();
        ttsPlayerRef.current?.stop();
        if (streamCancelRef.current) {
            streamCancelRef.current();
            streamCancelRef.current = null;
        }
        resetVoiceSession();
    }, [resetVoiceSession]);

    const bargeIn = useCallback(() => {
        if (ttsPlayerRef.current?.isPlaying) {
            ttsPlayerRef.current.stop();
            vlog('STATE', 'Barge-in: TTS stopped');
        }
        if (streamCancelRef.current) { streamCancelRef.current(); streamCancelRef.current = null; }
        setVoiceState(STATES.LISTENING);
    }, []);

    const handleFinalTranscript = useCallback(async (text, confidence = 0) => {
        if (!text.trim() || !voiceModeRef.current) return;
        const confStr = confidence > 0 ? (confidence * 100).toFixed(0) + '%' : 'N/A';
        trace('voice.finalTranscript', { text, confidence: confStr });
        vlog('STT', `Final: "${text}" (${confStr})`);

        if (holdToTextModeRef.current) {
            setVoiceTranscript(text);
            resetVoiceSession();
            onTranscriptReady?.(text, confidence);
            return;
        }

        setVoiceState(STATES.PROCESSING);
        setLiveTranscript('');
        setVoiceTranscript(text);

        if (doSendRef?.current) {
            vlog('STATE', `→ doSend: "${text.substring(0, 50)}"`);
            try {
                await doSendRef.current(text, true, confidence);
            } catch (err) {
                traceError('voice.doSendError', err, { text: text.substring(0, 60) });
                vlog('ERR', `doSend error: ${err.message}`);
            }
        }
    }, [doSendRef, onTranscriptReady, resetVoiceSession]);

    const startListening = useCallback(() => {
        if (!voiceModeRef.current) return;
        const recognizer = recognizerRef.current;
        if (!recognizer) return;

        vlog('STT', 'startListening()');
        heardSpeechRef.current = false;

        recognizer.setLang(toLanguageCode(languageRef.current));
        recognizer.onLiveTranscript = (text) => {
            setLiveTranscript(text);
            setIsListening(true);
            if (text && !/^🎤\s*Listening\.\.\.$/.test(text) && !/^⏳\s*Processing\.\.\.$/.test(text)) {
                heardSpeechRef.current = true;
            }
            if (holdToTextModeRef.current) {
                onTranscriptInterim?.(text);
            }
        };
        recognizer.onFinalTranscript = handleFinalTranscript;
        recognizer.onStateChange = (state) => {
            vlog('STATE', `STT → ${state}`);
            if (state === 'listening') { setVoiceState(STATES.LISTENING); setIsListening(true); }
            else if (state === 'idle') { setIsListening(false); }
        };
        recognizer.onSpeechDetected = () => {
            heardSpeechRef.current = true;
            if (voiceStateRef.current === STATES.SPEAKING) bargeIn();
        };
        recognizer.onStoppedWithoutTranscript = () => {
            if (holdToTextModeRef.current) {
                resetVoiceSession();
                onTranscriptCanceled?.();
            }
        };
        recognizer.onError = (err) => {
            vlog('ERR', `STT error: ${err}`);
            if (holdToTextModeRef.current) {
                resetVoiceSession();
                onTranscriptCanceled?.();
            }
            setVoiceTranscript('⚠️ ' + err);
            setTimeout(() => setVoiceTranscript(''), 4000);
        };

        recognizer.start();
    }, [handleFinalTranscript, bargeIn, onTranscriptCanceled, onTranscriptInterim, resetVoiceSession]);

    // Keep stable ref pointing to latest startListening
    startListeningRef.current = startListening;

    const speak = useCallback((text) => {
        if (!voiceModeRef.current || !text) return;
        ttsPlayerRef.current?.stop();
        vlog('TTS', `speak(): "${(text || '').substring(0, 60)}"`);
        setVoiceState(STATES.SPEAKING);

        const player = ttsPlayerRef.current;

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

        const lang = toLanguageCode(languageRef.current);
        vlog('TTS', `speak(..., { lang: '${lang}' })`);
        player.speak(text, { lang }).catch((err) => {
            vlog('ERR', `TTS speak error: ${err.message}`);
            restartListening();
        });
    }, [startListening]);

    const toggleVoiceMode = useCallback(async () => {
        if (voiceMode) {
            vlog('STATE', 'Voice OFF');
            stopVoiceSession();
        } else {
            vlog('STATE', 'Voice ON', { iOS: _isIOS });

            // Prime BOTH AudioContext and Audio element during this user gesture
            ttsPlayerRef.current?.primeForIOS();

            voiceModeRef.current = true;
            setVoiceMode(true);
            setVoiceState(STATES.LISTENING);

            // Request mic permission
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                stream.getTracks().forEach(t => t.stop());
                vlog('MIC', 'Mic permission granted');
            } catch (err) {
                vlog('ERR', `Mic permission: ${err.name} ${err.message}`);
                if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
                    setVoiceTranscript('⚠️ Microphone blocked — enable in settings');
                } else if (err.name === 'NotFoundError') {
                    setVoiceTranscript('⚠️ No microphone found');
                } else {
                    setVoiceTranscript('⚠️ Mic error: ' + (err.message || err.name));
                }
                setTimeout(() => setVoiceTranscript(''), 4000);
                return;
            }

            // Speak greeting — TTS will call restartListening when done
            const isTamil = languageRef.current === 'ta';
            const greet = isTamil
                ? "வணக்கம்! நீங்கள் என்ன சாப்பிட விரும்புகிறீர்கள்?"
                : "Hello! What would you like to eat?";
            speak(greet);
        }
    }, [voiceMode, speak, stopVoiceSession]);

    /**
     * Tap-to-dictate start.
     * Enables voice mode silently and streams speech into the chat composer.
     */
    const startDictation = useCallback(async () => {
        if (voiceModeRef.current) return; // already in voice mode
        vlog('DICTATION', 'startDictation()');

        ttsPlayerRef.current?.primeForIOS();

        // Request mic permission
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            stream.getTracks().forEach(t => t.stop());
        } catch (err) {
            vlog('ERR', `PTT mic permission: ${err.name}`);
            setVoiceTranscript('⚠️ Microphone blocked — enable in settings');
            setTimeout(() => setVoiceTranscript(''), 4000);
            return;
        }

        holdToTextModeRef.current = true;
        heardSpeechRef.current = false;
        voiceModeRef.current = true;
        setVoiceMode(true);
        setVoiceState(STATES.LISTENING);
        setLiveTranscript('');
        setVoiceTranscript('');
        startListeningRef.current?.();
    }, []);

    /**
     * Tap-to-dictate stop.
     * Finalizes recognition so the spoken words are preserved as text.
     */
    const stopDictation = useCallback(() => {
        if (!holdToTextModeRef.current) return;
        vlog('DICTATION', 'stopDictation()');

        if (!heardSpeechRef.current && !String(liveTranscript || '').trim() && !String(voiceTranscript || '').trim()) {
            recognizerRef.current?.stop();
            resetVoiceSession();
            onTranscriptCanceled?.();
            return;
        }

        setVoiceState(STATES.PROCESSING);
        setIsListening(false);
        if (typeof recognizerRef.current?.finish === 'function') {
            recognizerRef.current.finish();
        } else if (typeof recognizerRef.current?.stopRecording === 'function') {
            recognizerRef.current.stopRecording();
        } else {
            recognizerRef.current?.stop();
        }
    }, [liveTranscript, onTranscriptCanceled, resetVoiceSession, voiceTranscript]);

    const holdStart = startDictation;
    const holdEnd = stopDictation;

    return {
        voiceMode, setVoiceMode, voiceState, setVoiceState,
        liveTranscript, voiceTranscript, isListening,
        voiceModeRef, voiceStateRef,
        toggleVoiceMode, stopVoiceSession, speak, bargeIn, startListening,
        startDictation, stopDictation, holdStart, holdEnd,
        streamText: (text, callback) => {
            if (streamCancelRef.current) streamCancelRef.current();
            streamCancelRef.current = streamTextToCallback(text, callback);
        },
    };
}

export default useVoiceController;
