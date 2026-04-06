# Voice Order in Chat — Roadmap

## Overview

Add a **Voice Order** mode to the chat window that uses the same Retell AI / Vapi / browser fallback chain as the AI Call page. When a user taps "Voice Order" in the chat, a Retell realtime session starts *inline* — the AI handles ordering via tool calls, and transcripts flow into the chat message list.

## Why

The AI Call page uses managed voice providers (Retell → Vapi) which stream the full conversation loop (mic → STT → LLM with tool calls → TTS → speaker) at sub-100ms latency. The current chat voice uses Sarvam STT → fuzzy match → Sarvam TTS, which is slower (~2–3s per turn) and lacks the ordering intelligence. Users want that "too good" AI voice response quality *inside* the chat.

## Fallback Chain

```
1. Retell AI (streaming agent with tool calls)
   ↓ on error
2. Vapi (same capability, different provider)
   ↓ on error
3. Browser voice (existing Sarvam STT → chat engine → Sarvam TTS)
```

## Architecture

```
Chat Window (App.jsx)
  ├── Text mode (existing) — type + send
  ├── Dictation mode (existing) — mic → STT → text → send
  └── Voice Order mode (NEW) — Retell/Vapi realtime session
        ├── Reuses: createRealtimeCallRuntime()
        ├── Reuses: AI Call tool endpoints (/api/call-order/realtime/tools/*)
        ├── Reuses: parseRealtimeProviderMessage(), extractRealtimeToolCalls()
        ├── NEW: useVoiceOrderMode hook — session lifecycle in chat
        ├── NEW: transcript → chat messages adapter
        └── NEW: draft cart → main cart merge on session end
```

## What Is Reusable (Zero Changes)

| Module | What It Does |
|--------|-------------|
| `aiCall/realtimeRuntime.js` | Creates Retell or Vapi runtime |
| `aiCall/retellRuntime.js` | Retell WebClient SDK wrapper |
| `aiCall/vapiRuntime.js` | Vapi Web SDK wrapper |
| `aiCall/aiCallUtils.js` | Tool definitions, message parsing, prompt building |
| Backend `/api/call-order/realtime/*` | Session, web-call, tool endpoints |
| `api.js` realtime functions | `createAICallRealtimeSession`, `createRetellWebCall`, tool API calls |

## What Gets Built

### 1. `useVoiceOrderMode.js` hook (~200 lines)

Manages the Retell/Vapi realtime session lifecycle inside the chat:

- `startVoiceOrder()` — creates session, connects Retell (fallback Vapi → browser)
- `stopVoiceOrder()` — disconnects, merges draft cart → main cart
- Exposes: `{ isActive, isConnected, providerName, callState, draftCart, draftTotalCents, startVoiceOrder, stopVoiceOrder }`
- Handles `onMessage` — pipes transcripts into chat messages via callback
- Handles tool calls — executes them identically to AICallPage
- Handles `onError` — triggers fallback chain
- On session end — finalizes draft to authenticated cart

### 2. Voice Order UI overlay in `App.jsx`

- A "🎙️ Voice Order" button next to the mic button in the chat composer
- When active: compact overlay bar showing provider name, call state, end button
- Transcript messages appear in the normal chat message list
- Draft cart items shown in the existing cart panel

### 3. Test Cases

- Unit test for `useVoiceOrderMode` hook (session lifecycle, fallback chain)

## Implementation Order

1. Create `useVoiceOrderMode.js` hook
2. Wire into `App.jsx` — import hook, add button, connect callbacks
3. Add compact voice order overlay UI
4. Test fallback: Retell → Vapi → browser
5. Build verification

## Scope

- ~400 lines new code (mostly `useVoiceOrderMode.js`)
- ~30 lines UI additions in `App.jsx`
- No changes to backend endpoints
- No changes to existing voice, chat, or AI Call features
