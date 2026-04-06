# AI Call Ordering Roadmap

## Goal

Build a separate voice-first ordering experience that feels like a human call, without breaking or rewriting the current home, chat, menu, cart, or checkout flow.

## Non-Negotiables

- Keep the existing app flow intact.
- Add a separate entry point and separate page for call-based ordering.
- Reuse existing APIs only where safe.
- Do not let uncertain speech recognition turn into a blunt "not available" response.
- Confirm restaurant, item, quantity, and total before placing an order.

## Current Baseline In This Repo

- Frontend already has browser voice capture and playback support.
- Backend already has STT, TTS, and chat voice endpoints.
- Existing chat ordering flow already contains fuzzy matching and menu grounding.
- Existing app is a single-tab React shell, so a new isolated page can be added with low risk.

## Target Architecture

### Frontend

1. Add a dedicated `AI Call` entry point in the app shell.
2. Add a standalone `AICallPage` component instead of reusing the chat composer UI.
3. Show call state clearly: idle, listening, processing, speaking, error.
4. Show transcript history so users can verify what the AI heard.
5. Show a persistent note that this is the new voice-first flow.

### Backend

Phase 1 can reuse existing endpoints:

- `POST /api/voice/stt`
- `POST /api/voice/tts`
- `POST /api/voice/chat`

Phase 2 should add separate isolated APIs:

1. `POST /api/call-order/session`
2. `POST /api/call-order/turn`
3. `GET /api/call-order/session/:id`
4. `POST /api/call-order/session/:id/finalize`
5. `GET /api/call-order/admin/summary`

These should be implemented separately from the main typed-chat orchestration.

## Voice Matching Strategy For Indian Dishes

The assistant should never jump straight to "not available" when speech recognition is uncertain.

Recommended match ladder:

1. Exact match
2. Alias match
3. Spelling normalization
4. Phonetic normalization
5. Fuzzy match
6. LLM ranking over top candidates
7. Clarification question
8. Only then: unavailable

### Examples Of Required Normalization

- `kuzhambu`, `kulambu`, `kolambu`
- `kozhi`, `koli`
- `biryani`, `biriyani`, `briyani`
- `parotta`, `barotta`, `porotta`

### Response Policy

- High confidence: add/confirm directly.
- Medium confidence: ask `Did you mean ...?`
- Low confidence with candidates: present top 2 to 3 options.
- No likely candidates: ask user to repeat or suggest a nearby category.

## Implementation Phases

### Phase 1: Separate In-App Call MVP

Status: in progress

Scope:

1. Add a discoverable `AI Call` page in the app.
2. Keep existing tabs and UI intact.
3. Use current voice APIs for STT, TTS, and conversational replies.
4. Support Tamil and English selection.
5. Show transcript history and call state.
6. Keep this flow isolated from the current ordering UI.

Implemented now:

1. Separate `AI Call` tab and Home-tab entry card.
2. Standalone `AICallPage` UI.
3. Isolated backend session API: `POST /api/call-order/session`.
4. Isolated backend turn API: `POST /api/call-order/turn`.
5. Session snapshot API: `GET /api/call-order/session/:id`.
6. Suggestion cards on the new page for likely restaurant or dish matches.
7. Focused frontend and backend test coverage for the new isolated layer.

### Phase 2: Order-Aware Call Orchestrator

Scope:

1. Add isolated call session state.
2. Add restaurant/category/item context tracking.
3. Add draft order summary.
4. Add guarded add/remove/update quantity operations.
5. Add spoken confirmation before order placement.

Implemented now:

1. Draft cart is stored inside the isolated call session.
2. High-confidence item requests ask for confirmation before adding.
3. Confirmed items are added to the draft cart.
4. Remove-item voice requests update the draft cart.
5. The AI Call page now shows the draft order summary and pending confirmation state.
6. Confirmed draft items can now be moved into the existing authenticated cart.
7. The isolated call page can immediately reuse the existing checkout-session flow after materializing the draft cart.
8. Isolated call sessions are now persisted in the database so checkout return is not dependent on process memory.
9. Owner and admin users now have an isolated retention summary endpoint for persisted AI Call sessions.
10. The owner sales analytics view now surfaces the AI Call retention snapshot without changing the customer experience.
11. The retention summary now includes simple trend windows like sessions created in the last 24 hours, created in the last 7 days, and touched in the last 24 hours.

### Phase 3: Human-Like Reliability Improvements

Scope:

1. Alias dictionary for Indian dishes.
2. Phonetic normalization layer.
3. Confidence-based clarification rules.
4. Correction logging from real user sessions.
5. Better latency and barge-in behavior.

Implemented now:

1. The isolated AI Call matcher scores menu items against a bounded alias dictionary instead of only direct normalized text.
2. Added alias-family coverage for pairs like `kurma` and `korma`, `idiyappam` and `idiappom`, alongside the earlier biryani, parotta, and kuzhambu variants.
3. Added additional South Indian pronunciation coverage for families like `dosa` and `dosai`, `idli` and `idly`, `uthappam` and `uttapam`, and `vada` and `vadai`.
4. Added transcript-style matching for `Chicken 65` and `Gobi 65` spoken as `sixty five` or `six five`, and for `Chettinad` spelling variants like `chettinaad`.
5. Added conservative combo and platter matching for `thali` spelling variants and singular-plural `meal` forms like `Mini Meals` from `mini meal`.
6. Checkout success and cancellation now return localized AI Call-specific assistant copy in the transcript and voice playback path.
7. Added additional pronunciation coverage for `rasam` and `raasam`, `Poori` and `puri`, and `paneer` spoken as `panir` or `panneer`.
8. Added a regression test that forces clarification when multiple close item matches exist, so the assistant asks instead of guessing.

## Test Plan

### Unit Tests

1. Language normalization chooses only `en-IN` or `ta-IN`.
2. Call status labels map correctly to state.
3. Conversation context builder preserves the latest turns.
4. Voice UI helpers produce stable prompts for Tamil and English.

### Integration Tests

1. Start call from the new `AI Call` page.
2. Toggle mic permission failure and confirm error messaging.
3. Record an utterance, send to STT, get transcript, get TTS reply.
4. Switch language and confirm request payload changes.
5. End call and confirm audio and recorder cleanup.
6. Finalize a confirmed draft order into the authenticated cart.
7. Start checkout from the AI Call page and reuse the current checkout session flow.
8. Restore a call session after separate API requests and checkout return.
9. Expire stale persisted call sessions and remove them on access.
10. Browser-test the AI Call checkout return path for both payment success and payment cancellation.
11. Browser-test active AI Call ordering from spoken item request to confirmation to move-to-cart handoff.
12. Browser-test Tamil mode and remove-item behavior inside the isolated AI Call flow.
13. Verify owner/admin-only access and active-versus-expired counts for AI Call session retention observability.
14. Build-check the owner analytics UI after adding the AI Call retention card.
15. Browser-test multi-item AI Call drafts all the way into the shared cart UI.
16. Browser-test AI Call checkout cancellation with shared-cart continuity after redirect.
17. Browser-test AI Call payment success restoring shared order state in the app shell.
18. Browser-test the owner Sales analytics AI Call retention card and trend counters.
19. Browser-test at least one pronunciation-variant AI Call ordering path end to end.
20. Browser-test the ambiguity path where the assistant asks the user to choose between two close dish matches instead of guessing.

### Voice Matching Tests For Future Backend Work

1. `Nattu Kozhi Kuzhambu` matches `nattu koli kolambu`.
2. `Chicken Biryani` matches `chicken briyani`.
3. `Parotta` matches `barotta` and `porotta`.
4. `Masala Dosa` matches `masala dosai`.
5. `Idli` matches `idly`.
6. `Onion Uthappam` matches `onion uttapam`.
7. `Medu Vada` matches `medu vadai`.
8. `Chicken 65` matches `chicken sixty five`.
9. `Gobi 65` matches `gobi six five`.
10. `Chettinad Chicken` matches `chettinaad chicken`.
11. `South Indian Thali` matches `south indian thaali`.
12. `Mini Meals` matches `mini meal`.
13. `Chapathi` matches `chapati`.
14. `Mutton Sukka` matches `mutton chukka`.
15. `Veg Kurma` matches `veg kuruma`.
16. `Sambar Rice` matches `sambhar rice`.
17. `Tomato Rasam` matches `tomato raasam`.
18. `Poori` matches `puri`.
19. `Paneer Butter Masala` matches `panir butter masala`.
20. Ambiguous dish names return clarification instead of unavailability.
21. A real missing dish suggests close menu alternatives.

## Continuation Notes For Any Future Agent

1. Do not rewrite the current chat page to force call behavior into it.
2. Keep new work isolated in a separate page/component tree.
3. Prefer additive API changes over modifying existing ordering logic.
4. If expanding backend behavior, add a separate call-order orchestrator instead of overloading the current `/api/voice/chat` route.
5. If building dish alias support, store aliases separately from core item names so menu data stays canonical.

## Initial Files For This Track

- `docs/AI_CALL_ORDERING_ROADMAP.md`
- `frontend/src/AICallPage.jsx`
- `frontend/src/aiCall/aiCallUtils.js`
- `frontend/src/aiCall/aiCallUtils.test.js`
- `frontend/tests/ai-call-checkout.spec.cjs`
- `frontend/tests/ai-call-ordering-flow.spec.cjs`
- `frontend/tests/owner-ai-call-analytics.spec.cjs`
- `backend/app/call_order.py`
- `backend/tests/test_call_order.py`

## Next Recommended Steps After MVP

1. Expand the retention summary further if needed with longer-window trends or background cleanup metrics.
2. Expand the alias dictionary further from real call transcripts and correction data.
3. Improve barge-in and latency behavior for longer call sessions.
4. Add richer success-return continuity coverage if the redirect-based payment flow changes in the future.

## Latest Validation Snapshot

- Backend AI Call suite passes with 34 focused tests.
- Playwright coverage passes for AI Call checkout return success and cancellation.
- Playwright coverage passes for active AI Call ordering, Tamil mode, remove-item behavior, and multi-item draft handoff.
- Playwright coverage now also passes for the owner Sales analytics AI Call retention card and trend counters.
- Playwright coverage now also passes for a pronunciation-variant AI Call flow where spoken `puri` resolves to `Poori` and lands in the draft cart.
- Playwright coverage now also passes for a pronunciation-variant AI Call flow where spoken `panir butter masala` resolves to `Paneer Butter Masala` and lands in the draft cart.
- Playwright coverage now also passes for a pronunciation-variant AI Call flow where spoken `tomato raasam` resolves to `Tomato Rasam` and lands in the draft cart.
- Playwright coverage now also passes for the ambiguity path where spoken `dosa` produces a clarification between `Plain Dosa` and `Masala Dosa` without creating a pending add action.