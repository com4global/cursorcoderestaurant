"""
Chat engine with natural-language ordering, structured responses,
and voice-prompt support for conversational voice ordering.

Returns dicts with:
  - reply: text message
  - restaurant_id, category_id, order_id: session state
  - categories: list of category dicts (for interactive chips)
  - items: list of item dicts (for interactive cards)
  - voice_prompt: short TTS-friendly follow-up question for voice mode
"""
from __future__ import annotations

import re
from datetime import datetime
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from . import crud
from .models import ChatSession, MenuItem, Order


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(reply, restaurant_id=None, category_id=None, order_id=None,
            categories=None, items=None, cart_summary=None, voice_prompt=None):
    return {
        "reply": reply,
        "restaurant_id": restaurant_id,
        "category_id": category_id,
        "order_id": order_id,
        "categories": categories,
        "items": items,
        "cart_summary": cart_summary,
        "voice_prompt": voice_prompt,
    }


def _build_cart_summary_chat(db: Session, user_id: int) -> dict:
    """Build grouped cart summary for chat responses."""
    pending_orders = crud.get_user_pending_orders(db, user_id)
    groups = []
    grand_total = 0
    for order in pending_orders:
        from .models import Restaurant as RestModel
        restaurant = db.query(RestModel).filter(RestModel.id == order.restaurant_id).first()
        items = []
        for oi in order.items:
            mi = db.query(MenuItem).filter(MenuItem.id == oi.menu_item_id).first()
            line_total = oi.price_cents * oi.quantity
            items.append({
                "name": mi.name if mi else f"Item #{oi.menu_item_id}",
                "quantity": oi.quantity,
                "price_cents": oi.price_cents,
                "line_total_cents": line_total,
            })
        if items:
            groups.append({
                "restaurant_id": order.restaurant_id,
                "restaurant_name": restaurant.name if restaurant else "Unknown",
                "order_id": order.id,
                "items": items,
                "subtotal_cents": order.total_cents,
            })
            grand_total += order.total_cents
    return {"restaurants": groups, "grand_total_cents": grand_total}


def _set_session_state(db: Session, session: ChatSession, **updates) -> None:
    for key, value in updates.items():
        setattr(session, key, value)
    try:
        session.updated_at = datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
        # Commit may fail if table lacks status/updated_at: update only core columns via raw SQL
        from sqlalchemy import text
        allowed = {"restaurant_id", "category_id", "order_id"}
        set_parts = []
        params = {"sid": session.id}
        for k, v in updates.items():
            if k in allowed:
                set_parts.append(f"{k} = :{k}")
                params[k] = v
        if set_parts:
            db.execute(text(f"UPDATE chat_sessions SET {', '.join(set_parts)} WHERE id = :sid"), params)
            db.commit()
        else:
            raise


def _categories_data(db, restaurant_id):
    """Return categories as structured dicts with item counts."""
    categories = crud.list_categories(db, restaurant_id)
    result = []
    for cat in categories:
        items = crud.list_items(db, cat.id)
        result.append({
            "id": cat.id,
            "name": cat.name,
            "item_count": len(items),
        })
    return result


def _items_data(db, category_id):
    """Return items in a category as structured dicts."""
    items = crud.list_items(db, category_id)
    return [
        {
            "id": item.id,
            "name": item.name,
            "description": item.description or "",
            "price_cents": item.price_cents,
        }
        for item in items
    ]


def _build_voice_category_list(cats):
    """Build a short TTS-friendly list of category names."""
    names = [c["name"] for c in cats[:6]]
    if len(cats) > 6:
        return ", ".join(names) + f", and {len(cats) - 6} more"
    return ", ".join(names)


def _build_voice_item_list(items, limit=4):
    """Build a short TTS-friendly list of item names."""
    names = [it["name"] for it in items[:limit]]
    if len(items) > limit:
        return ", ".join(names) + f", and {len(items) - limit} more"
    return ", ".join(names)


# ---------------------------------------------------------------------------
# Smart restaurant matching from natural language
# ---------------------------------------------------------------------------

_RESTAURANT_INTENTS = [
    r"(?:order|eat|food|ordering|get food|get something)\s+(?:from|at|in)\s+(.+)",
    r"(?:i want to|i'd like to|let me|can i|could i)\s+(?:order|eat|get food|get something)\s+(?:from|at|in)\s+(.+)",
    r"(?:go to|open|select|pick|choose|show me)\s+(.+)",
    r"(?:take me to|switch to|change to)\s+(.+)",
]


def _extract_restaurant_name(text: str) -> str | None:
    """Extract restaurant name from natural language input."""
    lower = text.lower().strip()
    for pattern in _RESTAURANT_INTENTS:
        m = re.search(pattern, lower)
        if m:
            name = m.group(1).strip()
            # Clean trailing intent words
            for suffix in ["restaurant", "please", "menu", "and", "then"]:
                name = re.sub(rf'\s+{suffix}$', '', name).strip()
            if name:
                return name
    return None


def _extract_item_after_restaurant(text: str) -> str | None:
    """Extract item name from compound voice commands like 'order biryani from Desi District'."""
    lower = text.lower().strip()
    patterns = [
        r"(?:order|get|add|i want|give me|i'd like)\s+(.+?)\s+(?:from|at|in)\s+",
        r"(.+?)\s+(?:from|at|in)\s+",
    ]
    _INTENT_WORDS = {"order", "food", "eat", "something", "stuff", "anything",
                     "ordering", "get", "want", "like", "have", "need",
                     "i", "to", "some", "a", "an", "the", "me", "please",
                     "would", "could", "can", "let", "i'd", "i'll"}
    for pattern in patterns:
        m = re.search(pattern, lower)
        if m:
            item = m.group(1).strip()
            for filler in ["some", "a", "an", "the", "me", "to", "i want", "i'd like",
                           "please", "can i get", "can i have"]:
                item = re.sub(rf'^{re.escape(filler)}\s*', '', item).strip()
            if not item or len(item) <= 1:
                continue
            words = set(item.split())
            if words.issubset(_INTENT_WORDS):
                continue
            return item
    return None


def _find_best_restaurant(name: str, all_restaurants) -> object | None:
    """Fuzzy match a restaurant name."""
    name_lower = name.lower().strip()
    if not name_lower:
        return None

    # Exact slug or name match
    for r in all_restaurants:
        if r.slug == name_lower or r.name.lower() == name_lower:
            return r

    # Partial match
    for r in all_restaurants:
        if name_lower in r.name.lower() or r.name.lower() in name_lower:
            return r
        slug_clean = r.slug.replace('-', ' ')
        if name_lower in slug_clean or slug_clean in name_lower:
            return r

    # Fuzzy match
    best, best_score = None, 0.0
    for r in all_restaurants:
        score = max(
            _similarity(name_lower, r.name.lower()),
            _similarity(name_lower, r.slug.replace('-', ' ')),
        )
        if score > best_score:
            best_score = score
            best = r
    return best if best_score >= 0.5 else None


# Stop words shared with /search/menu-items in main.py
_CHAT_STOP_WORDS = {
    "i", "a", "an", "the", "is", "am", "are", "was", "were", "be", "been",
    "do", "does", "did", "have", "has", "had", "will", "would", "can",
    "could", "should", "may", "might", "shall", "to", "of", "in", "on",
    "at", "for", "with", "from", "by", "it", "its", "my", "me", "we",
    "us", "you", "your", "he", "she", "they", "them", "this", "that",
    "want", "need", "get", "find", "buy", "give", "show", "where",
    "what", "which", "how", "much", "many", "some", "any", "all",
    "please", "just", "like", "also", "very", "really", "about",
    "nearby", "near", "here", "around", "cheapest", "cheap", "compare",
    "price", "best", "value", "lowest",
}


def _edit_distance_chat(a: str, b: str) -> int:
    """Simple Levenshtein distance for fuzzy matching."""
    if len(a) < len(b):
        return _edit_distance_chat(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (0 if ca == cb else 1)))
        prev = curr
    return prev[len(b)]


def _fuzzy_match_chat(keyword: str, text: str) -> bool:
    """Check if keyword appears in text — exact substring OR fuzzy (edit distance ≤ threshold)."""
    if keyword in text:
        return True
    for word in text.split():
        word_clean = word.strip("(),.-!?").lower()
        if len(keyword) >= 3 and len(word_clean) >= 3:
            threshold = 1 if len(keyword) <= 5 else 2
            if _edit_distance_chat(keyword, word_clean) <= threshold:
                return True
    return False


def _search_items_across_restaurants(db: Session, query: str, restaurants, limit=5):
    """Search for items across all restaurants.

    Quality rules (matching /search/menu-items):
    1. Strip stop words from the query
    2. Exclude $0 items
    3. Require ALL keywords to match (exact or fuzzy)
    4. Sort by price ascending (cheapest first)
    """
    raw_keywords = query.lower().strip().split()
    keywords = [kw for kw in raw_keywords if kw not in _CHAT_STOP_WORDS and len(kw) >= 2]

    # Fallback: if all words were stop words, use the longest raw keyword
    if not keywords:
        keywords = sorted(raw_keywords, key=len, reverse=True)[:1]
    if not keywords:
        return []

    results = []
    for rest in restaurants:
        all_items = _get_all_restaurant_items(db, rest.id)
        for item in all_items:
            # Exclude $0 items
            if item.price_cents <= 0:
                continue
            item_name_lower = item.name.lower()
            # Require ALL keywords to match (exact or fuzzy)
            matched = sum(1 for kw in keywords if _fuzzy_match_chat(kw, item_name_lower))
            if matched == len(keywords):
                # Bonus for exact substring matches
                exact_bonus = sum(1 for kw in keywords if kw in item_name_lower)
                score = matched + exact_bonus
                results.append((item, rest, score))

    # Sort by match score DESC, then price ASC (cheapest first)
    results.sort(key=lambda x: (-x[2], x[0].price_cents))
    return results[:limit]


#
# Fuzzy item matching — IMPROVED for voice accuracy
# ---------------------------------------------------------------------------

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _token_match_score(query: str, item_name: str) -> float:
    """
    Token-level matching: check if query words appear as substrings
    or close matches of item name words. Much better for voice input
    where users say partial names like "chicken" for "Chicken Biryani".
    """
    query_tokens = query.lower().split()
    name_tokens = item_name.lower().split()
    if not query_tokens or not name_tokens:
        return 0.0

    matched_tokens = 0
    for qt in query_tokens:
        best_word_score = 0.0
        for nt in name_tokens:
            # Exact word match
            if qt == nt:
                best_word_score = 1.0
                break
            # Substring match
            if len(qt) >= 3 and (qt in nt or nt in qt):
                best_word_score = max(best_word_score, 0.85)
            # Fuzzy word match
            word_sim = _similarity(qt, nt)
            best_word_score = max(best_word_score, word_sim)
        if best_word_score >= 0.7:
            matched_tokens += 1

    # Score = ratio of matched query tokens
    return matched_tokens / len(query_tokens)


def _extract_item_phrase(text: str) -> str:
    """Strip order fillers and leading a/an to get the item name phrase for matching."""
    t = text.lower().strip()
    for filler in ["i want", "i'd like", "i would like", "give me", "get me",
                   "can i have", "can i get", "please", "order", "add", "i need", "i'll have", "i will have"]:
        t = re.sub(re.escape(filler), "", t, flags=re.IGNORECASE)
    t = t.strip().strip(",").strip()
    # Strip leading "a " / "an "
    for prefix in ("a ", "an "):
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
            break
    return t


def _extract_quantity_from_message(text: str) -> int:
    """Extract quantity from phrases like 'one iced coffee', 'two samosas', '3 biryani'."""
    word_to_num = {
        "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    lower = text.lower().strip()
    # Leading digit: "3 iced coffee" or "2x samosa"
    m = re.match(r'^(\d+)\s*(?:x\s*)?', lower)
    if m:
        return min(int(m.group(1)), 99)
    words = lower.split()
    if words and words[0] in word_to_num:
        return min(word_to_num[words[0]], 99)
    # "I would like one iced coffee" -> look for "one" anywhere
    for w in words:
        if w in word_to_num:
            return min(word_to_num[w], 99)
    return 1


def _llm_match_item(user_input: str, items: list[MenuItem]) -> MenuItem | None:
    """
    Use LLM to match customer message to a menu item. Pass full user message and all
    menu items so the model can resolve e.g. "one iced coffee" -> Iced Coffee (not the category).
    """
    if not items or not user_input.strip():
        return None

    try:
        from . import sarvam_service

        item_names = [f"{i+1}. {item.name}" for i, item in enumerate(items)]
        item_list_str = "\n".join(item_names)

        system_prompt = (
            "You are a menu item matcher for a restaurant. The user is viewing a list of menu items "
            "and said something. Match their message to ONE menu item from the list. "
            "Examples: 'I would like one iced coffee' -> match to 'Iced Coffee' (the drink), NOT a category. "
            "'Give me two samosas' -> match to the item that is samosa. "
            "Reply with ONLY the number of the matched item (1 to N). If they are NOT ordering an item "
            "(e.g. asking to change category or unclear), reply with 0. Do not explain."
        )

        context = f"Menu items in current category:\n{item_list_str}"
        user_msg = f"Customer said: \"{user_input}\""

        result = sarvam_service.chat_completion(user_msg, system_prompt, context)
        result = result.strip()

        import re as _re
        num_match = _re.search(r'\d+', result)
        if num_match:
            idx = int(num_match.group()) - 1
            if 0 <= idx < len(items):
                return items[idx]
    except Exception:
        import traceback
        traceback.print_exc()

    return None


def _llm_match_category(user_input: str, categories: list) -> object | None:
    """
    Use Sarvam AI LLM to intelligently match voice input against category names.
    """
    if not categories or not user_input.strip():
        return None

    try:
        from . import sarvam_service

        cat_names = [f"{i+1}. {cat['name'] if isinstance(cat, dict) else cat.name}" for i, cat in enumerate(categories)]
        cat_list_str = "\n".join(cat_names)

        system_prompt = (
            "You are a category matcher for a restaurant ordering system. "
            "The user is browsing categories via voice. Match their spoken input to the closest category. "
            "Reply with ONLY the number of the matched category. If no category matches, reply with 0. "
            "Be smart about voice transcription errors. "
            "Do not explain, just reply with the number."
        )

        context = f"Available categories:\n{cat_list_str}"
        user_msg = f"Customer said: \"{user_input}\""

        result = sarvam_service.chat_completion(user_msg, system_prompt, context)
        result = result.strip()

        import re as _re
        num_match = _re.search(r'\d+', result)
        if num_match:
            idx = int(num_match.group()) - 1
            if 0 <= idx < len(categories):
                return categories[idx]
    except Exception as e:
        import traceback
        traceback.print_exc()

    return None


def _compute_item_score(query: str, item: MenuItem) -> float:
    """Compute a combined score for an item match using multiple strategies."""
    query_lower = query.lower().strip()
    name_lower = item.name.lower()

    # Strategy 1: Exact full match
    if query_lower == name_lower:
        return 1.0

    # Strategy 2: Full substring match
    if query_lower in name_lower:
        # Longer substring = higher score
        return 0.85 + 0.1 * (len(query_lower) / len(name_lower))

    # Strategy 3: Reverse substring (item name in query)
    if name_lower in query_lower:
        return 0.80

    # Strategy 4: Token-level matching (best for voice)
    token_score = _token_match_score(query_lower, name_lower)

    # Strategy 5: Sequence matcher on full string
    seq_score = _similarity(query_lower, name_lower)

    # Take the best score
    return max(token_score * 0.9, seq_score)


def _find_best_item(query: str, all_items: list[MenuItem]) -> MenuItem | None:
    """Find the single best matching item. Higher threshold for voice accuracy."""
    query_lower = query.lower().strip()
    if not query_lower:
        return None

    # Exact match first
    for item in all_items:
        if item.name.lower() == query_lower:
            return item

    # Score all items
    scored = []
    for item in all_items:
        score = _compute_item_score(query_lower, item)
        if score >= 0.55:  # Voice-friendly: "ice coffee", "iced cofee" still match "Iced Coffee"
            scored.append((item, score))

    scored.sort(key=lambda x: x[1], reverse=True)

    if not scored:
        return None

    # If top match is strong enough (>= 0.75), return it directly
    if scored[0][1] >= 0.75:
        return scored[0][0]

    # If borderline (0.55-0.75), only return if it's clearly the best (voice typos: "ice coffee", "iced cofee")
    if len(scored) == 1:
        return scored[0][0]

    # If multiple items with similar scores, don't guess — return None
    # (caller should use _find_matching_items for disambiguation)
    if len(scored) >= 2 and scored[1][1] >= scored[0][1] * 0.85:
        return None  # Too ambiguous

    return scored[0][0]


def _find_matching_items(query: str, all_items: list[MenuItem], limit=5) -> list[MenuItem]:
    """Find multiple matching items for disambiguation."""
    query_lower = query.lower().strip()
    scored = []
    for item in all_items:
        score = _compute_item_score(query_lower, item)
        if score >= 0.40:
            scored.append((item, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [item for item, _ in scored[:limit]]


def _parse_order_items(text: str, all_items: list[MenuItem]) -> list[tuple[MenuItem, int]]:
    word_to_num = {
        "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }

    cleaned = text.lower().strip()
    for filler in ["i would like to order", "i want to order", "i'd like to order",
                   "i want", "i'd like", "i would like", "give me", "get me",
                   "can i have", "can i get", "please", "order", "add", "to order"]:
        cleaned = cleaned.replace(filler, "")
    cleaned = cleaned.strip().strip(",").strip()

    if not cleaned:
        return []

    parts = re.split(r'\s*(?:,\s*and|\band\b|,|&|\+)\s*', cleaned)

    results = []
    for part in parts:
        part = part.strip()
        if not part:
            continue

        quantity = 1
        num_match = re.match(r'^(\d+)\s+(.+)', part)
        if num_match:
            quantity = int(num_match.group(1))
            part = num_match.group(2).strip()
        else:
            words = part.split()
            if words and words[0] in word_to_num:
                quantity = word_to_num[words[0]]
                part = " ".join(words[1:]).strip()

        trailing = re.match(r'(.+?)\s*x\s*(\d+)$', part)
        if trailing:
            part = trailing.group(1).strip()
            quantity = int(trailing.group(2))

        item = _find_best_item(part, all_items)
        if item:
            results.append((item, quantity))

    return results


def _get_all_restaurant_items(db: Session, restaurant_id: int) -> list[MenuItem]:
    categories = crud.list_categories(db, restaurant_id)
    all_items = []
    for cat in categories:
        all_items.extend(crud.list_items(db, cat.id))
    return all_items


# ---------------------------------------------------------------------------
# Main message processor
# ---------------------------------------------------------------------------

def process_message(db: Session, session: ChatSession, text: str) -> dict:
    cleaned = text.strip()
    lower = cleaned.lower()

    # --- Reset / Exit (also clear cart so user truly starts fresh) ---
    if lower in ("#reset", "#exit", "reset", "exit", "start over"):
        crud.clear_user_pending_orders(db, session.user_id)
        _set_session_state(db, session, restaurant_id=None, category_id=None, order_id=None)
        return _result(
            "Session reset. Type # to pick a restaurant!",
            voice_prompt="Which restaurant would you like to order from?",
        )

    # --- Clear cart / order fresh (keep restaurant; clear all items) ---
    _clear_cart_phrases = (
        "clear cart", "clear the cart", "clear my cart", "empty cart", "empty the cart",
        "order fresh", "start fresh", "clear my order", "cancel my order", "remove all",
        "clear order", "cancel order", "clear all", "remove everything", "empty my order",
        "i want to clear the cart", "clear the order", "start a new order", "new order",
    )
    _clear_stripped = re.sub(r"^(?:i\s+want\s+to\s+|i'?d\s+like\s+to\s+|please\s+)\s*", "", lower).strip()
    # Voice often transcribes "cart" as "court" or "car"; allow "clear the court/car (completely)"
    _clear_cart_voice = (
        (lower.startswith("clear the ") or lower.startswith("clear my ") or lower.startswith("clear "))
        and any(w in lower for w in ("cart", "court", "car", "order", "all"))
    )
    if (lower.strip() in _clear_cart_phrases or _clear_stripped in _clear_cart_phrases
            or any(lower.startswith(p) for p in _clear_cart_phrases)
            or _clear_cart_voice):
        crud.clear_user_pending_orders(db, session.user_id)
        _set_session_state(db, session, order_id=None)
        cart = _build_cart_summary_chat(db, session.user_id)
        cats = _categories_data(db, session.restaurant_id) if session.restaurant_id else []
        return _result(
            "Cart cleared. What would you like to order?",
            restaurant_id=session.restaurant_id,
            category_id=session.category_id,
            categories=cats,
            cart_summary=cart,
            voice_prompt="Cart cleared. What would you like to order?",
        )

    # --- AI Budget Optimizer intent ---
    budget_patterns = [
        r'feed\s+(\d+)\s+people?\s+(?:for\s+)?(?:under\s+)?\$?(\d+)',
        r'meal\s+for\s+(\d+)\s+(?:people?\s+)?(?:under\s+)?\$?(\d+)',
        r'budget\s+(?:meal\s+)?(?:for\s+)?(\d+)\s+people?\s+\$?(\d+)',
        r'(\d+)\s+people?\s+(?:under\s+|for\s+|within\s+)\$?(\d+)',
        r'(?:order|food)\s+for\s+(\d+)\s+(?:people?\s+)?(?:under\s+)?\$?(\d+)',
    ]
    for bp in budget_patterns:
        budget_match = re.search(bp, lower)
        if budget_match:
            people = int(budget_match.group(1))
            budget_dollars = int(budget_match.group(2))
            budget_cents = budget_dollars * 100

            # Extract optional cuisine hint
            cuisine = None
            cuisine_match = re.search(r'(?:cuisine|type|style)[:\s]+(\w+)', lower)
            if not cuisine_match:
                for c in ["indian", "italian", "chinese", "mexican", "thai", "japanese", "american"]:
                    if c in lower:
                        cuisine = c.capitalize()
                        break
            else:
                cuisine = cuisine_match.group(1).capitalize()

            from . import optimizer
            results = optimizer.optimize_meal(
                db,
                people=people,
                budget_cents=budget_cents,
                cuisine=cuisine,
                restaurant_id=session.restaurant_id,
            )

            if not results:
                return _result(
                    f"Sorry, I couldn't find a meal combo for {people} people under ${budget_dollars}. "
                    f"Try increasing your budget or reducing the number of people.",
                    voice_prompt=f"I couldn't find a combo for {people} people under {budget_dollars} dollars. Try a higher budget.",
                )

            # Format the best combo
            best = results[0]
            lines = [f"💰 **Best combo at {best['restaurant_name']}:**\n"]
            for item in best["items"]:
                price = f"${item['price_cents'] * item['quantity'] / 100:.2f}"
                lines.append(f"  {item['quantity']}x {item['name']} — {price}")
            total = f"${best['total_cents'] / 100:.2f}"
            lines.append(f"\n**Total: {total}**")
            lines.append(f"**Feeds: {best['feeds_people']} people**")

            if len(results) > 1:
                lines.append(f"\n_({len(results) - 1} more option{'s' if len(results) > 2 else ''} available)_")

            reply = "\n".join(lines)
            voice_items = ", ".join(f"{i['quantity']} {i['name']}" for i in best["items"])
            voice = (
                f"Best combo at {best['restaurant_name']}. "
                f"{voice_items}. Total {total}, feeds {best['feeds_people']} people."
            )

            return _result(reply, voice_prompt=voice)

    # --- Restaurant selection via #slug ---
    if cleaned.startswith("#"):
        slug = cleaned.lstrip("#").strip().lower()
        if not slug:
            return _result(
                "Type # followed by a restaurant name to get started.",
                voice_prompt="Which restaurant would you like to order from?",
            )

        restaurant = crud.get_restaurant_by_slug_or_id(db, slug)
        if not restaurant:
            restaurants = crud.list_restaurants(db)
            for r in restaurants:
                if _similarity(slug, r.slug) >= 0.6 or _similarity(slug, r.name.lower()) >= 0.6:
                    restaurant = r
                    break

        if not restaurant:
            return _result(
                "Restaurant not found. Type # to see suggestions.",
                voice_prompt="I couldn't find that restaurant. Please say the name again.",
            )

        existing_order = crud.get_user_order_for_restaurant(db, session.user_id, restaurant.id)
        new_order_id = existing_order.id if existing_order else None
        _set_session_state(db, session, restaurant_id=restaurant.id, category_id=None, order_id=new_order_id)
        cats = _categories_data(db, restaurant.id)
        cart = _build_cart_summary_chat(db, session.user_id)

        cat_list = _build_voice_category_list(cats) if cats else "the menu"
        reply = f"Welcome to {restaurant.name}! Pick a category or just tell me what you want."
        return _result(
            reply, restaurant_id=restaurant.id, categories=cats, cart_summary=cart,
            voice_prompt=f"Welcome to {restaurant.name}. We have these categories: {cat_list}. Which one would you like?",
        )

    # --- If no restaurant selected yet: try smart matching ---
    if session.restaurant_id is None:
        all_restaurants = crud.list_restaurants(db)

        extracted_name = _extract_restaurant_name(cleaned)
        item_hint = _extract_item_after_restaurant(cleaned) if extracted_name else None

        candidate = extracted_name or cleaned
        restaurant = _find_best_restaurant(candidate, all_restaurants)

        if restaurant:
            existing_order = crud.get_user_order_for_restaurant(db, session.user_id, restaurant.id)
            new_order_id = existing_order.id if existing_order else None
            _set_session_state(db, session, restaurant_id=restaurant.id, category_id=None, order_id=new_order_id)
            cats = _categories_data(db, restaurant.id)
            cart = _build_cart_summary_chat(db, session.user_id)
            cat_list = _build_voice_category_list(cats) if cats else "the menu"

            # If compound command had an item hint, try to match it
            if item_hint:
                all_items = _get_all_restaurant_items(db, restaurant.id)
                parsed_items = _parse_order_items(item_hint, all_items)
                if parsed_items:
                    order = crud.get_user_order_for_restaurant(db, session.user_id, restaurant.id)
                    if not order:
                        order = crud.create_order(db, session.user_id, restaurant.id)
                    crud.attach_order_to_session(db, session, order)
                    added = []
                    for menu_item, qty in parsed_items:
                        crud.add_order_item(db, order, menu_item, qty)
                        added.append(f"  {qty}x {menu_item.name} - ${menu_item.price_cents * qty / 100:.2f}")
                    crud.recompute_order_total(db, order)
                    total = f"${order.total_cents / 100:.2f}"
                    cart = _build_cart_summary_chat(db, session.user_id)
                    added_names = ", ".join(m.name for m, _ in parsed_items)
                    reply = f"Welcome to {restaurant.name}!\n\nAdded to your order:\n" + "\n".join(added)
                    reply += f"\n\nCart total: {total}"
                    return _result(
                        reply, restaurant_id=restaurant.id, order_id=order.id,
                        categories=cats, cart_summary=cart,
                        voice_prompt=f"Added {added_names}. Want anything else, or say done to finish?",
                    )

                # Try matching as category
                categories = crud.list_categories(db, restaurant.id)
                for cat in categories:
                    if _similarity(item_hint.lower(), cat.name.lower()) >= 0.6:
                        items = _items_data(db, cat.id)
                        item_list = _build_voice_item_list(items)
                        return _result(
                            f"Welcome to {restaurant.name}!\n\n{cat.name} — {len(items)} items. Tap + to add or tell me what you want!",
                            restaurant_id=restaurant.id, category_id=cat.id, order_id=new_order_id,
                            categories=cats, items=items, cart_summary=cart,
                            voice_prompt=f"{cat.name}. Which one would you like?",
                        )

                # Try fuzzy item search as fallback
                matches = _find_matching_items(item_hint, all_items)
                if matches:
                    items_data = [
                        {"id": m.id, "name": m.name, "description": m.description or "", "price_cents": m.price_cents}
                        for m in matches
                    ]
                    match_names = ", ".join(m.name for m in matches[:3])
                    return _result(
                        f'Welcome to {restaurant.name}!\n\nFound {len(matches)} items matching "{item_hint}". Tap + to add!',
                        restaurant_id=restaurant.id, order_id=new_order_id,
                        categories=cats, items=items_data, cart_summary=cart,
                        voice_prompt=f"I found these items: {match_names}. Which one would you like?",
                    )

            reply = f"Welcome to {restaurant.name}! Pick a category or just tell me what you want."
            return _result(
                reply, restaurant_id=restaurant.id, categories=cats, cart_summary=cart,
                voice_prompt=f"Welcome to {restaurant.name}. We have: {cat_list}. Which category would you like?",
            )

        # No restaurant match — try cross-restaurant item search
        if all_restaurants and len(cleaned) > 2:
            cross_results = _search_items_across_restaurants(db, cleaned, all_restaurants)
            if cross_results:
                # Extract meaningful keywords for display
                raw_kws = cleaned.lower().split()
                display_kws = [kw for kw in raw_kws if kw not in _CHAT_STOP_WORDS and len(kw) >= 2]
                display_query = " ".join(display_kws) if display_kws else cleaned
                lines = [f'Found "{display_query}" at these restaurants:\n']
                seen = set()
                rest_names = []
                for item, rest, score in cross_results:
                    if rest.id not in seen:
                        lines.append(f"• **{rest.name}** — {item.name} (${item.price_cents/100:.2f})")
                        rest_names.append(rest.name)
                        seen.add(rest.id)
                lines.append(f'\nSay the restaurant name or type #{cross_results[0][1].slug} to order!')
                return _result(
                    "\n".join(lines),
                    voice_prompt=f"I found that item at: {', '.join(rest_names[:3])}. Which restaurant would you like?",
                )

        # Final fallback
        if all_restaurants:
            suggestions = [f"• {r.name} — #{r.slug}" for r in all_restaurants[:5]]
            rest_names = ", ".join(r.name for r in all_restaurants[:5])
            return _result(
                "I couldn't find that restaurant. Available options:\n\n" + "\n".join(suggestions)
                + "\n\nSay a restaurant name or type # to browse!",
                voice_prompt=f"I couldn't find that. Available restaurants are: {rest_names}. Which one?",
            )
        return _result(
            "No restaurants available. Add your zipcode to find nearby options!",
            voice_prompt="No restaurants found in your area. Please set your location first.",
        )

    # --- Browse category by name or id ---
    if lower.startswith("category:") or lower.startswith("browse:"):
        cat_query = cleaned.split(":", 1)[1].strip()
        # If session has a restaurant_id, scope to it
        if session.restaurant_id:
            categories = crud.list_categories(db, session.restaurant_id)
        else:
            categories = []
        match = None
        for cat in categories:
            if str(cat.id) == cat_query or cat.name.lower() == cat_query.lower():
                match = cat
                break
        # Fallback: try to find category by ID directly
        if not match and cat_query.isdigit():
            from .models import MenuCategory as CatModel
            direct_cat = db.query(CatModel).filter(CatModel.id == int(cat_query)).first()
            if direct_cat:
                # Only accept the category if it belongs to the current restaurant
                # (prevents cross-restaurant menu leaks)
                if session.restaurant_id and direct_cat.restaurant_id != session.restaurant_id:
                    direct_cat = None  # Wrong restaurant — ignore
                if direct_cat:
                    match = direct_cat
                    # Also fix the session restaurant_id if it was missing
                    if not session.restaurant_id:
                        _set_session_state(db, session, restaurant_id=direct_cat.restaurant_id)
                        categories = crud.list_categories(db, direct_cat.restaurant_id)
        if match:
            _set_session_state(db, session, category_id=match.id)
            items = _items_data(db, match.id)
            cats = _categories_data(db, session.restaurant_id or match.restaurant_id)
            return _result(
                f"{match.name} — {len(items)} items. Tap + to add or just tell me what you want!",
                restaurant_id=session.restaurant_id,
                category_id=match.id,
                order_id=session.order_id,
                categories=cats,
                items=items,
                voice_prompt=f"{match.name}, {len(items)} items. Which one?",
            )
        # No match: avoid falling through into code that assumes session.restaurant_id
        return _result(
            "That category isn't available. Pick a category above or say a dish name.",
            restaurant_id=session.restaurant_id,
            category_id=session.category_id,
            order_id=session.order_id,
            voice_prompt="Pick another category or tell me what you'd like.",
        )

    # --- Quick add by item ID (from tapping + button) ---
    quick_add = re.match(r'^add:(\d+)(?::(\d+))?$', lower)
    if quick_add:
        item_id = int(quick_add.group(1))
        quantity = int(quick_add.group(2) or 1)
        all_items = _get_all_restaurant_items(db, session.restaurant_id)
        menu_item = next((i for i in all_items if i.id == item_id), None)
        if menu_item:
            order = crud.get_user_order_for_restaurant(db, session.user_id, session.restaurant_id)
            if not order:
                order = crud.create_order(db, session.user_id, session.restaurant_id)
            crud.attach_order_to_session(db, session, order)

            order_item = crud.add_order_item(db, order, menu_item, quantity)
            crud.recompute_order_total(db, order)
            total = f"${order.total_cents / 100:.2f}"
            qty_msg = f" Now {order_item.quantity}x in cart." if order_item.quantity > 1 else ""
            cart = _build_cart_summary_chat(db, session.user_id)
            return _result(
                f"Added {quantity}x {menu_item.name}!{qty_msg} Cart total: {total}",
                restaurant_id=session.restaurant_id,
                order_id=order.id,
                cart_summary=cart,
                voice_prompt=f"Added {menu_item.name}. Want anything else, or say done?",
            )
        return _result(
            "Item not found.",
            restaurant_id=session.restaurant_id,
            voice_prompt="I couldn't find that item. What would you like to add?",
        )

    # --- Change restaurant / go back (when user wants to switch restaurant) ---
    if session.restaurant_id:
        change_restaurant_phrases = (
            "change restaurant", "different restaurant", "go back", "switch restaurant",
            "other restaurant", "another restaurant", "new restaurant", "back to restaurants",
            "show restaurants", "list restaurants", "which restaurants",
            "change the restaurant", "switch the restaurant", "chain restaurant",
        )
        # Exact, startswith, contains, or voice-friendly: "change"/"switch"/"different" + "restaurant"
        has_change_restaurant = "change" in lower and "restaurant" in lower
        has_switch_restaurant = "switch" in lower and "restaurant" in lower
        # Tamil: "சேஞ்ச்"/"சேன்ஜ்" = change, "ரெஸ்டாரண்ட்" = restaurant; "சேஞ்ச் த" = "change the" (partial)
        tamil_change = any(
            s in cleaned for s in ("சேஞ்ச்", "சேன்ஜ்", "மாற்ற")
        ) or ("ரெஸ்டாரண்ட்" in cleaned and ("சேஞ்ச்" in cleaned or "சேன்ஜ்" in cleaned or "மாற்ற" in cleaned))
        wants_change = (
            lower.strip() in change_restaurant_phrases
            or any(lower.startswith(p) for p in change_restaurant_phrases)
            or any(p in lower for p in (
                "different restaurant", "change restaurant", "another restaurant",
                "other restaurant", "switch restaurant", "back to restaurants",
                "show restaurants", "list restaurants", "new restaurant",
                "want to change restaurant", "like to change restaurant",
                "pick another restaurant", "choose another restaurant",
                "go back to restaurants", "see other restaurants",
            ))
            or has_change_restaurant
            or has_switch_restaurant
            or (("different" in lower or "another" in lower or "other" in lower) and "restaurant" in lower)
            or tamil_change
        )
        if wants_change:
            _set_session_state(db, session, restaurant_id=None, category_id=None, order_id=None)
            all_restaurants = crud.list_restaurants(db)
            rest_names = ", ".join(r.name for r in all_restaurants[:6])
            suggestions = [f"• {r.name} — #{r.slug}" for r in all_restaurants[:6]]
            return _result(
                "Which restaurant would you like?\n\n" + "\n".join(suggestions),
                restaurant_id=None,
                voice_prompt=f"Which restaurant would you like? We have: {rest_names}.",
            )

    # --- General search while in a restaurant: "cheap biryani nearby" / "restaurants with X" ---
    if session.restaurant_id and len(cleaned) > 3:
        discovery_hints = ("nearby", "near me", "cheap", "cheapest", "restaurants that", "restaurants with",
                          "where can i get", "where can i find", "who has", "which restaurant has")
        if any(h in lower for h in discovery_hints):
            all_restaurants = crud.list_restaurants(db)
            cross_results = _search_items_across_restaurants(db, cleaned, all_restaurants)
            if cross_results:
                _set_session_state(db, session, restaurant_id=None, category_id=None, order_id=None)
                display_kws = " ".join(w for w in lower.split() if w not in _CHAT_STOP_WORDS and len(w) >= 2)
                lines = [f'Found "{display_kws}" at these restaurants:\n']
                seen = set()
                rest_names = []
                for item, rest, score in cross_results:
                    if rest.id not in seen:
                        lines.append(f"• **{rest.name}** — {item.name} (${item.price_cents/100:.2f})")
                        rest_names.append(rest.name)
                        seen.add(rest.id)
                lines.append(f'\nSay the restaurant name or type #{cross_results[0][1].slug} to order!')
                return _result(
                    "\n".join(lines),
                    restaurant_id=None,
                    voice_prompt=f"I found that at: {', '.join(rest_names[:3])}. Which restaurant would you like?",
                )

    # --- When items are already displayed (user is in a category): try ITEM first (add to cart), then category (switch) ---
    all_items = _get_all_restaurant_items(db, session.restaurant_id)
    categories = crud.list_categories(db, session.restaurant_id)
    category_items = [i for i in all_items if session.category_id and i.category_id == session.category_id]

    # When user is viewing a category's items: try FAST path first (fuzzy/token), LLM only as fallback
    # so e.g. "iced coffee" -> instant match; "I would like one iced coffee" -> parse_order_items or LLM
    item_parsed = []
    if session.category_id and category_items:
        # Direct name match first for ANY order phrase ("I want iced coffee", "give me a cappuccino", etc.)
        phrase = _extract_item_phrase(cleaned)
        if phrase:
            for item in category_items:
                iname = item.name.lower()
                # Full match, or item name in phrase, or phrase in item name (handles voice/typos)
                if phrase == iname or iname in phrase or phrase in iname:
                    item_parsed = [(item, max(1, _extract_quantity_from_message(cleaned)))]
                    break
            # If no exact/substring match, try longest item name contained in phrase (e.g. "large iced coffee" -> "Iced Coffee")
            if not item_parsed and len(phrase) > 3:
                best_item, best_len = None, 0
                for item in category_items:
                    iname = item.name.lower()
                    if iname in phrase and len(iname) > best_len:
                        best_item, best_len = item, len(iname)
                if best_item:
                    item_parsed = [(best_item, max(1, _extract_quantity_from_message(cleaned)))]
        if not item_parsed:
            item_parsed = _parse_order_items(cleaned, category_items)
        if not item_parsed:
            single = _find_best_item(cleaned, category_items)
            if single:
                item_parsed = [(single, max(1, _extract_quantity_from_message(cleaned)))]
        if not item_parsed:
            llm_item = _llm_match_item(cleaned, category_items)
            if llm_item:
                qty = _extract_quantity_from_message(cleaned)
                item_parsed = [(llm_item, max(1, qty))]
    if not item_parsed:
        item_parsed = _parse_order_items(cleaned, all_items)
        if not item_parsed:
            single = _find_best_item(cleaned, all_items)
            if single:
                item_parsed = [(single, 1)]
        if not item_parsed:
            llm_item = _llm_match_item(cleaned, all_items)
            if llm_item:
                item_parsed = [(llm_item, 1)]

    if item_parsed:
        order = crud.get_user_order_for_restaurant(db, session.user_id, session.restaurant_id)
        if not order:
            order = crud.create_order(db, session.user_id, session.restaurant_id)
        crud.attach_order_to_session(db, session, order)
        added_lines, added_names = [], []
        for menu_item, qty in item_parsed:
            crud.add_order_item(db, order, menu_item, qty)
            price = f"${menu_item.price_cents * qty / 100:.2f}"
            added_lines.append(f"  {qty}x {menu_item.name} - {price}")
            added_names.append(menu_item.name)
        crud.recompute_order_total(db, order)
        total = f"${order.total_cents / 100:.2f}"
        reply = "Added to your order:\n" + "\n".join(added_lines)
        reply += f"\n\nCart total: {total}"
        cart = _build_cart_summary_chat(db, session.user_id)
        voice_added = ", ".join(added_names)
        return _result(
            reply,
            restaurant_id=session.restaurant_id,
            order_id=order.id,
            cart_summary=cart,
            categories=_categories_data(db, session.restaurant_id),
            items=_items_data(db, session.category_id) if session.category_id else None,
            voice_prompt=f"Added {voice_added}. Want anything else, or say done to finish?",
        )

    # --- No item match: try CATEGORY match (so user can say "starters" to switch category) ---
    cat_match = None
    category_query = lower
    for prefix in (
        "show me ", "show ", "open ", "open the ", "browse ", "display ", "see ",
        "i want to see ", "i want ", "can i see ", "let me see ", "give me the ",
    ):
        if category_query.startswith(prefix):
            category_query = category_query[len(prefix):].strip()
            break
    category_query = category_query.strip()
    input_words = category_query.split() if category_query else lower.split()
    q = category_query or lower

    for cat in categories:
        if cat.name.lower() == lower or str(cat.id) == lower or (category_query and cat.name.lower() == category_query):
            cat_match = cat
            break
    if not cat_match and len(input_words) == 1:
        for cat in categories:
            cat_lower = cat.name.lower()
            cat_words = [w.strip() for w in cat_lower.replace("/", " ").split()]
            iw = input_words[0]
            for cw in cat_words:
                if len(iw) >= 2 and (iw in cw or cw in iw):
                    cat_match = cat
                    break
                if len(iw) >= 2 and _similarity(iw, cw) >= 0.7:
                    cat_match = cat
                    break
            if cat_match:
                break
    if not cat_match:
        best_cat, best_score = None, 0.0
        for cat in categories:
            cat_lower = cat.name.lower()
            score = max(_similarity(q, cat_lower), _similarity(lower, cat_lower))
            if len(input_words) == 1:
                for word in cat_lower.replace("/", " ").split():
                    word = word.strip()
                    if word:
                        score = max(score, _similarity(q, word), _similarity(input_words[0], word))
            if score > best_score:
                best_score = score
                best_cat = cat
        # Only treat as category if input isn't more specific than category name (e.g. "iced coffee" vs "Coffee" = item)
        cat_words = len(best_cat.name.split()) if best_cat else 0
        if best_score >= 0.55 and len(input_words) <= cat_words:
            cat_match = best_cat
    # When already in a category, don't use LLM for multi-word input — likely an item name ("iced coffee")
    if not cat_match and not (session.category_id and len(cleaned.split()) >= 2):
        cat_match = _llm_match_category(cleaned, categories)

    # Do not re-select the same category (e.g. "iced coffee" matched category "Coffee")
    if cat_match and session.category_id and cat_match.id == session.category_id:
        cat_match = None

    if cat_match:
        _set_session_state(db, session, category_id=cat_match.id)
        items = _items_data(db, cat_match.id)
        return _result(
            f"{cat_match.name} — {len(items)} items. Tap + to add or tell me the item name.",
            restaurant_id=session.restaurant_id,
            category_id=cat_match.id,
            order_id=session.order_id,
            categories=_categories_data(db, session.restaurant_id),
            items=items,
            voice_prompt=f"{cat_match.name}. {len(items)} items. Which one would you like?",
        )

    # --- No item and no category match: fall through to "didn't catch" / show menu ---

    # --- Show menu / categories ---
    if lower in ("menu", "show menu", "categories", "show categories", "what do you have"):
        cats = _categories_data(db, session.restaurant_id)
        cat_list = _build_voice_category_list(cats)
        return _result(
            "Here are the categories. Tap one to browse!",
            restaurant_id=session.restaurant_id,
            order_id=session.order_id,
            categories=cats,
            voice_prompt=f"We have these categories: {cat_list}. Which one would you like?",
        )

    # --- Submit order ---
    if lower in ("#order", "submit", "submit order", "place order", "done",
                 "checkout", "check out", "that's all", "thats all", "confirm",
                 "place my order", "send order", "i'm done", "im done",
                 "finished", "that is all", "no more", "nothing else"):
        if session.order_id is None:
            cats = _categories_data(db, session.restaurant_id)
            cat_list = _build_voice_category_list(cats)
            return _result(
                "Your cart is empty! Pick a category or tell me what you want.",
                restaurant_id=session.restaurant_id,
                voice_prompt=f"Your cart is empty. We have: {cat_list}. What would you like to order?",
            )
        order = crud.get_order(db, session.order_id)
        if not order:
            _set_session_state(db, session, order_id=None)
            return _result(
                "Cart not found. Tell me what you want to order!",
                restaurant_id=session.restaurant_id,
                voice_prompt="Your cart seems empty. What would you like to order?",
            )
        order.status = "submitted"
        db.commit()
        total = f"${order.total_cents / 100:.2f}"
        return _result(
            f"Order #{order.id} submitted! Total: {total}. Your order has been sent to the restaurant!",
            restaurant_id=session.restaurant_id,
            order_id=order.id,
            voice_prompt=f"Your order has been placed! Total is {total}. Thank you!",
        )

    # --- View cart (multi-restaurant) ---
    if lower in ("cart", "my cart", "show cart", "view cart", "what's in my cart"):
        pending_orders = crud.get_user_pending_orders(db, session.user_id)
        if not pending_orders:
            return _result(
                "Your cart is empty! Just tell me what you want.",
                restaurant_id=session.restaurant_id,
                voice_prompt="Your cart is empty. What would you like to order?",
            )
        lines = ["🛒 **Your Cart:**\n"]
        grand_total = 0
        item_names_for_voice = []
        from .models import Restaurant as RestModel
        for order in pending_orders:
            if not order.items:
                continue
            rest = db.query(RestModel).filter(RestModel.id == order.restaurant_id).first()
            rest_name = rest.name if rest else "Unknown"
            lines.append(f"**{rest_name}:**")
            for oi in order.items:
                mi = db.query(MenuItem).filter(MenuItem.id == oi.menu_item_id).first()
                name = mi.name if mi else f"Item #{oi.menu_item_id}"
                lines.append(f"  {oi.quantity}x {name} - ${oi.price_cents * oi.quantity / 100:.2f}")
                item_names_for_voice.append(f"{oi.quantity} {name}")
            lines.append(f"  Subtotal: ${order.total_cents / 100:.2f}\n")
            grand_total += order.total_cents
        if grand_total == 0:
            return _result(
                "Your cart is empty!",
                restaurant_id=session.restaurant_id,
                voice_prompt="Your cart is empty. What would you like to order?",
            )
        lines.append(f"**Grand Total: ${grand_total / 100:.2f}**")
        lines.append('\nSay "submit" to place your order!')
        cart = _build_cart_summary_chat(db, session.user_id)
        total_str = f"${grand_total / 100:.2f}"
        voice_items = ", ".join(item_names_for_voice[:4])
        return _result(
            "\n".join(lines),
            restaurant_id=session.restaurant_id,
            order_id=session.order_id,
            cart_summary=cart,
            voice_prompt=f"Your cart has: {voice_items}. Total is {total_str}. Say done to place the order, or add more items.",
        )


    # --- Natural language ordering ---
    all_items = _get_all_restaurant_items(db, session.restaurant_id)
    parsed = _parse_order_items(cleaned, all_items)

    if not parsed:
        single_match = _find_best_item(cleaned, all_items)
        if single_match:
            parsed = [(single_match, 1)]

    if not parsed:
        # Don't treat clarification words as item search ("what", "huh" → helpful prompt)
        _clarification_words = (
            "what", "huh", "sorry", "pardon", "eh", "repeat", "again",
            "hello", "hey", "wait", "um", "ok", "yeah",
        )
        if cleaned.lower().strip() in _clarification_words:
            cats = _categories_data(db, session.restaurant_id)
            return _result(
                "You can say a category name, an item to add, or **done** to finish.",
                restaurant_id=session.restaurant_id,
                order_id=session.order_id,
                categories=cats,
                voice_prompt="Say a category or item name, or say done to finish.",
            )

        # Try search and show matching items for disambiguation
        matches = _find_matching_items(cleaned, all_items)
        if matches:
            items_data = [
                {
                    "id": m.id,
                    "name": m.name,
                    "description": m.description or "",
                    "price_cents": m.price_cents,
                }
                for m in matches
            ]
            match_names = ", ".join(m.name for m in matches[:3])
            return _result(
                f'Found {len(matches)} items matching "{cleaned}". Tap + to add!',
                restaurant_id=session.restaurant_id,
                order_id=session.order_id,
                items=items_data,
                voice_prompt=f"Did you mean: {match_names}? Please say the exact item name.",
            )

        # Show categories as fallback (no full list in TTS — keep it short)
        cats = _categories_data(db, session.restaurant_id)
        return _result(
            "I didn't catch that. Pick a category or type what you want!",
            restaurant_id=session.restaurant_id,
            order_id=session.order_id,
            categories=cats,
            voice_prompt="I didn't catch that. Pick a category or say the item name.",
        )

    # Create or get order (per-restaurant)
    order = crud.get_user_order_for_restaurant(db, session.user_id, session.restaurant_id)
    if not order:
        order = crud.create_order(db, session.user_id, session.restaurant_id)
    crud.attach_order_to_session(db, session, order)

    added_lines = []
    added_names = []
    for menu_item, qty in parsed:
        crud.add_order_item(db, order, menu_item, qty)
        price = f"${menu_item.price_cents * qty / 100:.2f}"
        added_lines.append(f"  {qty}x {menu_item.name} - {price}")
        added_names.append(menu_item.name)

    crud.recompute_order_total(db, order)
    total = f"${order.total_cents / 100:.2f}"
    reply = "Added to your order:\n" + "\n".join(added_lines)
    reply += f"\n\nCart total: {total}"

    cart = _build_cart_summary_chat(db, session.user_id)
    voice_added = ", ".join(added_names)
    return _result(
        reply,
        restaurant_id=session.restaurant_id,
        order_id=order.id,
        cart_summary=cart,
        voice_prompt=f"Added {voice_added}. Want anything else, or say done to finish?",
    )
