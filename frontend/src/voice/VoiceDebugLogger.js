/**
 * VoiceDebugLogger.js — On-screen debug overlay for iOS voice troubleshooting
 * 
 * Shows a small floating panel in the bottom-left with timestamped voice events.
 * Activated by adding ?voicedebug=1 to the URL (won't show in normal use).
 * 
 * Usage:
 *   import { vlog } from './VoiceDebugLogger.js';
 *   vlog('STT', 'recognition started');
 *   vlog('TTS', 'play() called', { src: url });
 *   vlog('ERR', 'play() blocked', { error: e.message });
 */

let _overlay = null;
let _enabled = null;
const MAX_LINES = 40;
const _lines = [];

function isEnabled() {
    if (_enabled !== null) return _enabled;
    try {
        const params = new URLSearchParams(window.location.search);
        _enabled = params.get('voicedebug') === '1';
    } catch {
        _enabled = false;
    }
    return _enabled;
}

function getOverlay() {
    if (_overlay) return _overlay;
    if (typeof document === 'undefined') return null;

    _overlay = document.createElement('div');
    _overlay.id = 'voice-debug-overlay';
    Object.assign(_overlay.style, {
        position: 'fixed',
        bottom: '60px',
        left: '4px',
        width: '340px',
        maxHeight: '280px',
        overflowY: 'auto',
        background: 'rgba(0,0,0,0.88)',
        color: '#0f0',
        fontFamily: 'monospace',
        fontSize: '10px',
        lineHeight: '1.3',
        padding: '6px 8px',
        borderRadius: '8px',
        zIndex: '99999',
        pointerEvents: 'auto',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        border: '1px solid rgba(0,255,0,0.3)',
    });
    document.body.appendChild(_overlay);
    return _overlay;
}

const TAG_COLORS = {
    STT: '#0ff',
    TTS: '#f0f',
    ERR: '#f44',
    MIC: '#ff0',
    STATE: '#8f8',
    IOS: '#fa0',
};

/**
 * Log a voice debug event to the on-screen overlay + console.
 * @param {string} tag - Category: STT, TTS, ERR, MIC, STATE, IOS
 * @param {string} message - Human-readable message
 * @param {object} [data] - Optional extra data
 */
export function vlog(tag, message, data) {
    const time = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const extra = data ? ' ' + JSON.stringify(data) : '';
    const line = `${time} [${tag}] ${message}${extra}`;

    // Always log to console
    const color = TAG_COLORS[tag] || '#fff';
    console.log(`%c[VoiceDebug] ${line}`, `color: ${color}; font-size: 11px`);

    if (!isEnabled()) return;

    _lines.push(line);
    if (_lines.length > MAX_LINES) _lines.shift();

    const overlay = getOverlay();
    if (overlay) {
        overlay.textContent = _lines.join('\n');
        overlay.scrollTop = overlay.scrollHeight;
    }
}

/** Force enable/disable the overlay (useful for programmatic control). */
export function setVoiceDebugEnabled(enabled) {
    _enabled = enabled;
    if (!enabled && _overlay) {
        _overlay.remove();
        _overlay = null;
    }
}

export default vlog;
