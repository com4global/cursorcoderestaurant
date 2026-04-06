/**
 * trace.js — Browser console tracing for voice/chat debugging
 *
 * When testing manually:
 * 1. Open DevTools (F12) → Console
 * 2. Filter by "Trace" to see only trace logs
 * 3. Reproduce the issue — each step logs a [Trace] tag + payload
 * 4. Copy-paste the trace lines (or save console) when reporting issues
 *
 * Tags: doSend.entry, voice.validation, voice.rejected, intent.parsed,
 *       guard.noRestaurant, backend.send, backend.response, backend.error,
 *       voice.finalTranscript, voice.doSendComplete, voice.doSendError
 *
 * Usage: trace('tag', { key: value, ... })
 */

const PREFIX = '[Trace]';
const ENABLED = true; // set to false to disable all trace logs

export function trace(tag, data = {}) {
  if (!ENABLED || typeof console === 'undefined') return;
  const ts = new Date().toISOString().slice(11, 23);
  const payload = typeof data === 'object' && data !== null && Object.keys(data).length > 0
    ? { ts, tag, ...data }
    : { ts, tag, msg: data };
  console.log(`${PREFIX} ${tag}`, payload);
}

export function traceError(tag, err, extra = {}) {
  if (!ENABLED || typeof console === 'undefined') return;
  const ts = new Date().toISOString().slice(11, 23);
  console.error(`${PREFIX} ${tag}`, { ts, tag, error: err?.message || String(err), stack: err?.stack, ...extra });
}

/** Log elapsed ms since start (for voice latency debugging). Use: const t0 = performance.now(); ... traceTiming('stepName', t0); */
export function traceTiming(step, startTime, extra = {}) {
  if (!ENABLED || typeof console === 'undefined') return;
  const elapsedMs = Math.round((performance.now() - startTime) * 10) / 10;
  const payload = { step, elapsedMs, ts: new Date().toISOString().slice(11, 23), ...extra };
  console.log(`${PREFIX} voice.timing`, payload);
  return elapsedMs;
}

export default trace;
