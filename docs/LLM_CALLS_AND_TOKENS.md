# When We Call LLM (OpenAI / Sarvam AI) and Token Usage

## Summary

| Where | Provider | When | Max output tokens | Typical input (approx) |
|-------|----------|------|-------------------|------------------------|
| **chat.py** | Sarvam | Item match fallback | 200 | ~200–500 |
| **chat.py** | Sarvam | Category match fallback | 200 | ~150–300 |
| **voice.py** | Sarvam | `/api/voice/chat` (optional) | 200 | ~100–400 |
| **optimizer.py** | Sarvam | Meal combo explanation | 200 | ~150–250 |
| **intent_extractor.py** | OpenAI or Sarvam | **Not used** (use_llm=False in main) | 300 (OpenAI) | ~500 |
| **menu_extractor.py** | OpenAI | Menu from image (vision) | 16,000 | image + ~200 |

---

## 1. Sarvam AI (`sarvam_service.py`)

**Model:** `sarvam-m`  
**Config:** `max_tokens=200`, `temperature=0.7`  
**Endpoint:** `POST https://api.sarvam.ai/v1/chat/completions`

### When we call it

| Call site | When it runs | Input | Output |
|-----------|----------------|-------|--------|
| **chat.py `_llm_match_item()`** | Only when user is in a category and fuzzy/parse fail to match an item (e.g. “one iced coffee” with many items). | System: short matcher instructions. Context: numbered list of item names. User: customer message. | Single number (1–N) or 0. |
| **chat.py `_llm_match_category()`** | Only when we have categories but no backend category match (e.g. voice says “starters” and we need to map to “Appetizers”). | System: short category matcher instructions. Context: numbered list of category names. User: customer message. | Single number (1–N) or 0. |
| **voice.py `POST /api/voice/chat`** | When the client explicitly calls this endpoint (e.g. `voiceChat(message, context)` in `api.js`). Not used in the main ordering flow today. | System: short assistant instructions. Context: optional. User: message. | Short conversational reply. |
| **optimizer.py `_generate_explanation()`** | After meal optimizer finds a combo; used to generate a short recommendation text. | Single user-style prompt describing combo + budget + “write 2–3 sentences”. | 2–3 sentence recommendation. |
| **intent_extractor `_call_sarvam()`** | Only if `extract_intent(text, use_llm=True)` is used. **Main app uses `use_llm=False`**, so this path is not used in normal chat/search. | System: intent schema + rules. User: raw text. | JSON object. |

### Tokens per Sarvam call (approximate)

- **Input:** System + context + user message. Depends on number of items/categories and message length.
  - Item match: system ~40, context ~50–150 (e.g. 10–30 items), user ~10–30 → **~100–250 input**.
  - Category match: system ~35, context ~20–80 (e.g. 5–15 categories), user ~10–25 → **~65–140 input**.
  - Voice /chat: **~100–400 input** (depends on context).
  - Optimizer: **~150–250 input** (combo + instructions).
- **Output:** Capped at **200 tokens**; actual replies are usually a few tokens (e.g. a number or a short paragraph).

---

## 2. OpenAI

### 2a. Intent extractor (`intent_extractor.py`)

- **When:** Only if code calls `extract_intent(text, use_llm=True)`.  
- **Current usage:** `main.py` uses `extract_intent(text, use_llm=False)`, so **no LLM call** in the main flow.
- **If enabled:** Tries OpenAI first (`gpt-4o-mini`), then Sarvam fallback.
  - **OpenAI:** `max_tokens=300`, `response_format={"type": "json_object"}`.  
  - **Input:** System prompt (~400 tokens) + user text.  
  - **Output:** JSON intent object (up to 300 tokens).

### 2b. Menu extractor (`menu_extractor.py`)

- **When:** Owner imports menu from an **image** (e.g. photo of menu) and image-based extraction is used.
- **Model:** `gpt-4o-mini` (vision).
- **Input:** System extraction prompt + user message + **image (base64)**. Image size dominates token count (vision models count image tokens).
- **Output:** `max_tokens=16000` (large to allow full menu JSON). Actual usage depends on menu size.

---

## 3. Non-LLM Sarvam APIs (no chat tokens)

These use Sarvam but are **not** chat/completion LLM; they don’t use the token counts above:

- **STT:** `POST /speech-to-text` (Saaras v3) – audio in, transcript out.  
- **TTS:** `POST /text-to-speech` (Bulbul v3) – text in, audio out.  

They are billed separately by Sarvam (e.g. per minute / per character), not as chat tokens.

---

## 4. Code references

| File | Function / endpoint | LLM |
|------|---------------------|-----|
| `backend/app/sarvam_service.py` | `chat_completion()` | Sarvam `sarvam-m`, max 200 tokens |
| `backend/app/chat.py` | `_llm_match_item()`, `_llm_match_category()` | Sarvam (item/category fallback) |
| `backend/app/voice.py` | `POST /api/voice/chat` | Sarvam |
| `backend/app/optimizer.py` | `_generate_explanation()` | Sarvam |
| `backend/app/intent_extractor.py` | `_call_openai()`, `_call_sarvam()` | OpenAI then Sarvam (not used when use_llm=False) |
| `backend/app/menu_extractor.py` | Image menu extraction | OpenAI gpt-4o-mini vision, max 16k tokens |

---

## 5. Per user action (typical ordering flow)

For a **single voice or text order** (e.g. “add iced coffee”):

- **Best case:** No LLM. Fuzzy/item parse and category logic handle it → **0 tokens**.
- **Worse case:** No item match → one **Sarvam** `_llm_match_item` call → **~100–250 input, ≤200 output**.

So in the main flow, **at most one Sarvam chat call per message**, and only when local matching fails. Intent extraction does **not** call the LLM because `use_llm=False`.
