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
    }, [doSendRef]);

    const startListening = useCallback(() => {
        if (!voiceModeRef.current) return;
        const recognizer = recognizerRef.current;
        if (!recognizer) return;

        vlog('STT', 'startListening()');

        recognizer.setLang(languageRef.current === 'ta' ? 'ta-IN' : 'en-IN');
        recognizer.onLiveTranscript = (text) => { setLiveTranscript(text); setIsListening(true); };
        recognizer.onFinalTranscript = handleFinalTranscript;
        recognizer.onStateChange = (state) => {
            vlog('STATE', `STT → ${state}`);
            if (state === 'listening') { setVoiceState(STATES.LISTENING); setIsListening(true); }
            else if (state === 'idle') { setIsListening(false); }
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

        const lang = languageRef.current === 'ta' ? 'ta-IN' : 'en-IN';
        player.speak(text, { lang }).catch((err) => {
            vlog('ERR', `TTS speak error: ${err.message}`);
            restartListening();
        });
    }, [startListening]);

    const toggleVoiceMode = useCallback(async () => {
        if (voiceMode) {
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
            const greet = languageRef.current === 'ta'
                ? "வணக்கம்! நீங்கள் என்ன சாப்பிட விரும்புகிறீர்கள்?"
                : "Hello! What would you like to eat?";
            speak(greet);
        }
    }, [voiceMode, speak]);

    return {
        voiceMode, voiceState, setVoiceState,
        liveTranscript, voiceTranscript, isListening,
        voiceModeRef, voiceStateRef,
        toggleVoiceMode, speak, bargeIn, startListening,
        streamText: (text, callback) => {
            if (streamCancelRef.current) streamCancelRef.current();
            streamCancelRef.current = streamTextToCallback(text, callback);
        },
    };
}

export default useVoiceController;
