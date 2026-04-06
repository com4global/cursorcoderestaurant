# AI Call Realtime Implementation Plan

## Scope

This plan applies only to the isolated AI Call feature.

Do not change:

- existing typed chat flows
- existing cart and checkout behavior
- owner/admin analytics outside AI Call
- other voice endpoints used elsewhere in the app

The current turn-based `STT -> backend turn -> TTS` flow is not sufficient for human-like interaction.
To reach that level, AI Call needs a dedicated realtime voice architecture with interruption handling, low latency, and tool-calling.

## Goal

Create a human-like AI ordering call that:

- listens continuously after the call starts
- responds when the user stops speaking
- supports interruption and barge-in
- remembers context across turns
- uses tools for menu lookup, order changes, and checkout handoff
- remains fully isolated from the current non-call experiences

## Recommended Architecture

### Best Practical Option

Use a managed realtime voice orchestration layer for AI Call only.

Recommended candidates:

1. `Vapi`
2. `Retell AI`

These platforms already solve the hardest parts:

- streaming STT
- interruption handling
- realtime TTS playback
- latency management
- call session state hooks
- tool calling / function calling

The existing FastAPI backend should remain the system of record for:

- restaurant data
- menu items
- draft cart state
- final cart materialization
- checkout handoff

### Alternative Option

Build a self-orchestrated realtime stack with:

- streaming STT: Sarvam streaming when available, or Deepgram / Whisper streaming
- reasoning: GPT-4o Realtime or Claude via a server orchestration layer
- expressive TTS: ElevenLabs, Cartesia, or Sarvam if expressive streaming is sufficient

This gives more control but is substantially more work.

## Recommendation

For this repo, the fastest reliable path is:

1. keep the existing AI Call UI shell
2. replace the current HTTP turn loop only for AI Call
3. add a dedicated realtime voice session path
4. expose backend tool endpoints to the voice agent
5. preserve the current cart and checkout mechanics

## Target System Design

### Frontend

Add a dedicated AI Call realtime client layer, scoped only to the AI Call page.

Suggested files:

- `frontend/src/aiCall/useRealtimeCall.js`
- `frontend/src/aiCall/realtimeProvider.js`
- `frontend/src/AICallPage.jsx` integration updates only

Frontend responsibilities:

- open and close realtime session
- show call status: listening, thinking, speaking, interrupted
- stream mic audio to the provider
- play streamed TTS audio
- handle barge-in visually and functionally
- render transcript and tool-driven clarifications

### Backend

Add a dedicated router for AI Call realtime orchestration.

Suggested files:

- `backend/app/ai_call_realtime.py`
- `backend/app/ai_call_tools.py`

Backend responsibilities:

- issue session tokens / ephemeral session config for the realtime provider
- provide tool endpoints for the agent
- validate any requested restaurant/item/cart mutations
- persist the AI Call session state
- keep final checkout handoff unchanged

### Data Flow

1. user opens AI Call page
2. frontend requests a realtime AI Call session from backend
3. backend returns provider session config
4. frontend connects mic + audio stream to provider
5. provider performs streaming STT, reasoning, and TTS
6. provider calls backend tools when needed
7. backend validates and returns structured tool results
8. provider continues the conversation naturally
9. finalized confirmed items are handed into the existing cart / checkout flow

## Tooling Model

The realtime agent should not directly mutate orders. It should call tools.

Recommended AI Call-only tools:

1. `find_restaurants(query)`
2. `get_restaurant_menu(restaurant_id, query=None)`
3. `suggest_menu_items(restaurant_id, query)`
4. `add_draft_item(session_id, item_id, quantity)`
5. `remove_draft_item(session_id, item_id, quantity)`
6. `get_draft_summary(session_id)`
7. `finalize_draft_to_cart(session_id, user_id)`
8. `start_checkout(session_id, user_id)`

Optional later tools:

1. `check_inventory(item_id)`
2. `get_eta(zipcode)`
3. `get_order_status(order_id)`
4. `create_recovery_offer(reason)`

## Conversation Design

The AI Call agent should be instructed to:

- ask one question at a time
- never guess an item silently
- clarify ambiguous dish names before acting
- preserve current restaurant context unless the user clearly switches
- handle natural corrections like `actually make that two`
- answer exploratory questions like `what are the naan options`
- confirm before any draft cart mutation unless the user gave a direct, high-confidence repeatable order

## Session State

Keep the existing AI Call session model as the base and expand it only for AI Call.

Suggested additions:

- `conversation_stage`
- `clarification_candidates_json`
- `last_tool_result_json`
- `provider_session_id`

These fields should live only in the AI Call session record path.

## Migration Plan

### Phase 1

Provider abstraction only.

- add realtime provider config
- add backend session bootstrap endpoint
- add backend tool endpoints
- keep current AI Call page intact
- add feature flag: `AI_CALL_REALTIME_ENABLED`

### Phase 2

Wire frontend AI Call page to realtime provider.

- mic streaming
- streamed transcript
- streamed assistant speech
- interruption handling
- draft cart tool calls

### Phase 3

Retire the current AI Call turn-based loop behind the feature flag.

- old path remains fallback
- realtime path becomes primary when enabled

## Recommended Feature Flags

- `AI_CALL_REALTIME_ENABLED=false`
- `AI_CALL_PROVIDER=vapi`
- `AI_CALL_PROVIDER_API_KEY=...`

If self-orchestrated later:

- `AI_CALL_STREAMING_STT_PROVIDER=sarvam|deepgram`
- `AI_CALL_STREAMING_TTS_PROVIDER=sarvam|elevenlabs|cartesia`
- `AI_CALL_REASONING_PROVIDER=openai|anthropic`

## Why This Is Better Than The Current Loop

The current model has unavoidable limits:

- recording starts and stops per turn
- first syllables can be clipped
- TTS and microphone timing can race each other
- latency compounds because each turn waits for four separate steps

A realtime architecture fixes the core problem rather than patching symptoms.

## Immediate Next Step

Implement Phase 1 only:

1. add provider abstraction
2. add AI Call realtime session bootstrap route
3. add AI Call tool routes
4. keep all existing non-AI-Call features untouched
