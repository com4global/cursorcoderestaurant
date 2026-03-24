# Voice latency optimization (feature/voice-latency-optimization)

## Summary

Faster perceived response when using **voice to select categories and menu items** that are already on screen. No change to behavior for general search, restaurant switch, or typed input.

## Changes

### 1. Category selection by voice
- **Before:** Voice match → wait for `sendMessage("category:ID")` → then TTS and items.
- **After:** Voice match → **TTS immediately** ("Appetizers. Which one would you like?") → load items via **REST** (`/categories/:id/items`) in parallel → session sync via `sendMessage` in background.
- **Effect:** User hears the category name and sees the menu as soon as the REST call returns (no wait for chat backend).

### 2. Item selection by voice (add from current menu)
- **New fast path:** When user has a category open (`currentItems` set) and says an item name (e.g. "biryani", "add biryani", "one chicken curry"), we **match locally** against `currentItems` (fuzzy by name).
- If exactly one match (or one best match): **TTS immediately** ("Added Biryani.") → send `add:itemId:1` to backend → update cart when response returns.
- **Effect:** No backend "understanding" delay; add-to-cart is a single small request.

### 3. Intent parser preload
- When voice mode is turned **on**, we preload `IntentParser.js` and `ConversationState.js` so the first voice command does not pay dynamic-import cost.

## What is unchanged

- General search, "change restaurant", greeting/help/thanks/goodbye, meal plan, cart/checkout flows.
- When the user says something that does **not** match a displayed category or item, the message still goes to `process_message` (backend) as before.
- Text (typed) input behavior is unchanged; category match now also uses REST + background session for consistency.

## Deployment

Use branch **feature/voice-latency-optimization** for deployment. Merge to `main` after validation.
