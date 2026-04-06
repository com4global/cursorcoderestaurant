/**
 * VoicePipelineLog.jsx — Real-time voice pipeline debug panel
 *
 * Shows a scrollable overlay with every step of the voice flow:
 *   MIC → STT → INTENT → ROUTE → BACKEND → RESPONSE → TTS
 *
 * Activate: click the 🔍 debug button (shown when voice is active) or add ?voicelog=1 to URL
 *
 * Usage from anywhere in the app:
 *   import { pipelineLog } from './voice/VoicePipelineLog.jsx';
 *   pipelineLog('STT', 'Final transcript', { text: '...', confidence: 0.92 });
 */

import { useState, useEffect, useRef, useCallback } from 'react';

// ─── Shared log store (module-level singleton) ───
const MAX_ENTRIES = 200;
let _entries = [];
let _listeners = new Set();
let _idCounter = 0;

const STEP_COLORS = {
  MIC:      '#ffcc00',
  STT:      '#00ccff',
  INTENT:   '#cc66ff',
  ROUTE:    '#ff9900',
  SEND:     '#66ccff',
  BACKEND:  '#00ff88',
  RESPONSE: '#88ff44',
  TTS:      '#ff66cc',
  CART:     '#ffaa00',
  ERROR:    '#ff4444',
  STATE:    '#aaaaaa',
  SEARCH:   '#44ddff',
  MATCH:    '#88aaff',
  WARN:     '#ffaa44',
};

const STEP_ICONS = {
  MIC:      '🎤',
  STT:      '📝',
  INTENT:   '🧠',
  ROUTE:    '🔀',
  SEND:     '📤',
  BACKEND:  '⚙️',
  RESPONSE: '📥',
  TTS:      '🔊',
  CART:     '🛒',
  ERROR:    '❌',
  STATE:    '⚡',
  SEARCH:   '🔍',
  MATCH:    '🎯',
  WARN:     '⚠️',
};

/**
 * Log a voice pipeline step. Call from anywhere.
 * @param {'MIC'|'STT'|'INTENT'|'ROUTE'|'SEND'|'BACKEND'|'RESPONSE'|'TTS'|'CART'|'ERROR'|'STATE'|'SEARCH'|'MATCH'|'WARN'} step
 * @param {string} message - Human-readable description
 * @param {object} [data] - Optional structured data
 */
export function pipelineLog(step, message, data) {
  const now = new Date();
  const ts = now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
    + '.' + String(now.getMilliseconds()).padStart(3, '0');
  const entry = { id: ++_idCounter, ts, step, message, data: data || null };

  _entries.push(entry);
  if (_entries.length > MAX_ENTRIES) _entries = _entries.slice(-MAX_ENTRIES);

  // Console output (always, for DevTools)
  const icon = STEP_ICONS[step] || '📋';
  const color = STEP_COLORS[step] || '#ccc';
  const dataStr = data ? ' ' + JSON.stringify(data, null, 0) : '';
  console.log(
    `%c${icon} [VoicePipeline] ${ts} [${step}] ${message}${dataStr}`,
    `color: ${color}; font-weight: bold; font-size: 11px`
  );

  // Notify React subscribers
  _listeners.forEach((fn) => fn([..._entries]));
}

/** Clear all log entries */
export function clearPipelineLog() {
  _entries = [];
  _listeners.forEach((fn) => fn([]));
}

/** Get current entries (for non-React consumers) */
export function getPipelineEntries() {
  return [..._entries];
}

// ─── React Component ───

export default function VoicePipelineLog({ visible, onClose }) {
  const [entries, setEntries] = useState(() => [..._entries]);
  const [filter, setFilter] = useState('ALL');
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef(null);

  useEffect(() => {
    const handler = (newEntries) => setEntries(newEntries);
    _listeners.add(handler);
    return () => _listeners.delete(handler);
  }, []);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [entries, autoScroll]);

  const filtered = filter === 'ALL' ? entries : entries.filter((e) => e.step === filter);

  const handleScroll = useCallback(() => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 40);
  }, []);

  if (!visible) return null;

  return (
    <div style={{
      position: 'fixed', bottom: 0, left: 0, right: 0,
      height: '45vh', minHeight: '200px',
      background: 'rgba(10, 10, 20, 0.96)',
      color: '#e0e0e0',
      fontFamily: "'SF Mono', 'Fira Code', 'Consolas', monospace",
      fontSize: '11px',
      zIndex: 100000,
      display: 'flex', flexDirection: 'column',
      borderTop: '2px solid #333',
      backdropFilter: 'blur(8px)',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '8px',
        padding: '6px 12px',
        background: 'rgba(30, 30, 50, 0.9)',
        borderBottom: '1px solid #333',
        flexShrink: 0,
      }}>
        <span style={{ fontWeight: 'bold', color: '#00ccff' }}>🔍 Voice Pipeline Log</span>

        {/* Filter buttons */}
        <div style={{ display: 'flex', gap: '2px', marginLeft: '12px', flexWrap: 'wrap' }}>
          {['ALL', 'MIC', 'STT', 'INTENT', 'ROUTE', 'SEND', 'BACKEND', 'RESPONSE', 'TTS', 'ERROR'].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              style={{
                padding: '1px 6px', fontSize: '10px',
                background: filter === f ? (STEP_COLORS[f] || '#555') : '#222',
                color: filter === f ? '#000' : (STEP_COLORS[f] || '#999'),
                border: `1px solid ${STEP_COLORS[f] || '#444'}`,
                borderRadius: '3px', cursor: 'pointer',
              }}
            >{f}</button>
          ))}
        </div>

        <div style={{ flex: 1 }} />
        <span style={{ color: '#666', fontSize: '10px' }}>{filtered.length} entries</span>
        <button onClick={clearPipelineLog} style={{
          padding: '2px 8px', fontSize: '10px', background: '#333',
          color: '#ff8888', border: '1px solid #555', borderRadius: '3px', cursor: 'pointer',
        }}>Clear</button>
        <button onClick={onClose} style={{
          padding: '2px 8px', fontSize: '10px', background: '#333',
          color: '#fff', border: '1px solid #555', borderRadius: '3px', cursor: 'pointer',
        }}>✕</button>
      </div>

      {/* Log entries */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        style={{
          flex: 1, overflowY: 'auto', padding: '4px 8px',
          scrollBehavior: 'smooth',
        }}
      >
        {filtered.length === 0 && (
          <div style={{ color: '#666', padding: '20px', textAlign: 'center' }}>
            No voice pipeline events yet. Start speaking to see logs.
          </div>
        )}
        {filtered.map((entry) => (
          <div key={entry.id} style={{
            padding: '2px 0',
            borderBottom: '1px solid rgba(255,255,255,0.04)',
            lineHeight: '1.4',
          }}>
            <span style={{ color: '#666' }}>{entry.ts}</span>
            {' '}
            <span style={{ color: STEP_COLORS[entry.step] || '#ccc', fontWeight: 'bold' }}>
              {STEP_ICONS[entry.step] || '📋'} [{entry.step}]
            </span>
            {' '}
            <span style={{ color: '#e0e0e0' }}>{entry.message}</span>
            {entry.data && (
              <span style={{ color: '#888', marginLeft: '8px' }}>
                {JSON.stringify(entry.data)}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
