# Vapi to Retell Migration Roadmap (AI Call)

## Goal
Migrate the isolated AI Call realtime flow from Vapi to Retell while preserving:
- human-like conversational behavior
- low-latency interruption handling
- existing restaurant/menu/cart tool behavior
- zero impact on non-AI-Call experiences

## Scope
In scope:
- `frontend/src/AICallPage.jsx`
- `frontend/src/aiCall/*`
- `backend/app/ai_call_realtime.py`
- `backend/app/config.py`
- AI Call realtime tests and provider-config expectations

Out of scope:
- chat page behavior
- non-AI-call cart/checkout APIs
- owner analytics logic

## Phase 1: Provider Abstraction (Safe Foundation)
1. Introduce provider-agnostic realtime runtime factory in frontend.
2. Keep Vapi runtime path unchanged and default.
3. Add Retell runtime adapter scaffold and message parser.
4. Make `AICallPage` consume provider runtime via provider name from backend.

Acceptance criteria:
- With `AI_CALL_PROVIDER=vapi`, behavior remains unchanged.
- Realtime provider name is surfaced in UI status/debug path.

## Phase 2: Backend Provider Configuration
1. Expand backend settings with Retell fields (agent ids, webhook secret/url).
2. Return provider-specific session bootstrap config from `/api/call-order/realtime/session`.
3. Keep existing tool endpoints unchanged.

Acceptance criteria:
- Session bootstrap returns valid provider config for Vapi and Retell.
- Missing-field diagnostics identify misconfiguration clearly.

## Phase 3: Tool Call Compatibility Layer
1. Generalize tool execution dispatcher (`_execute_realtime_tool`).
2. Keep Vapi webhook route intact.
3. Add Retell webhook route and normalize incoming tool call shapes.

Acceptance criteria:
- Existing Vapi tool calls continue to work.
- Retell webhook can execute `list_restaurants`, `find_restaurants`, `get_restaurant_menu`, `get_draft_summary`, `add_draft_item`, `remove_draft_item`.

## Phase 4: Prompt and Voice Parity Tuning
1. Reuse current strict system prompt and tool rules.
2. Keep one-tool-at-a-time queue semantics.
3. Tune interruption and silence/endpointer settings to match existing call feel.

Acceptance criteria:
- A/B calls have no major degradation in interruption handling.
- Tool accuracy and cart mutation behavior match existing flow.

## Phase 5: Rollout and Guardrails
1. Feature-flag rollout by environment.
2. Keep fast fallback path to local voice mode on provider failure.
3. Add smoke tests for provider bootstrap and draft-cart tool sequence.

Acceptance criteria:
- Provider switch is config-only in staging.
- Failures degrade gracefully without blocking ordering.

## Implementation Notes
- Keep `AI_CALL_PROVIDER=vapi` as initial default to avoid production regression.
- Enable Retell in staging first with representative restaurant calls.
- Track latency, tool-call success rate, order accuracy, and fallback rate before production cutover.
