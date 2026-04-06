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
from math import asin, cos, radians, sin, sqrt
from datetime import datetime
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from . import crud
from .models import ChatSession, MenuItem, Order, Restaurant
from .multi_order_extractor import extract_multi_order


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
            price_cents = oi.price_cents or 0
            # Fix likely double-converted price (e.g. 129900 instead of 1299)
            if price_cents >= 10000 and price_cents % 100 == 0:
                candidate = price_cents // 100
                if 1 <= candidate <= 10000:
                    price_cents = candidate
            line_total = price_cents * oi.quantity
            items.append({
                "order_item_id": oi.id,
                "name": mi.name if mi else f"Item #{oi.menu_item_id}",
                "quantity": oi.quantity,
                "price_cents": price_cents,
                "line_total_cents": line_total,
            })
        if items:
            subtotal = sum(i["line_total_cents"] for i in items)
            groups.append({
                "restaurant_id": order.restaurant_id,
                "restaurant_name": restaurant.name if restaurant else "Unknown",
                "order_id": order.id,
                "items": items,
                "subtotal_cents": subtotal,
            })
            grand_total += subtotal
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

_TAMIL_SCRIPT_RE = re.compile(r'[\u0B80-\u0BFF]')
_MIXED_ORDER_CONNECTORS = (
    "அப்புறம்", "அதுக்கப்புறம்", "பிறகு", "மற்றும்", "அடுத்து", "கூட",
)


def _debug_log_mixed_order(stage: str, **fields) -> None:
    parts = []
    for key, value in fields.items():
        if value is None:
            continue
        text = str(value).replace("\n", " ").strip()
        if len(text) > 240:
            text = text[:237] + "..."
        parts.append(f"{key}={text}")
    suffix = " | " + " | ".join(parts) if parts else ""
    print(f"[chat.mixed-order] {stage}{suffix}")


def _should_try_mixed_order_normalization(text: str, session_has_restaurant: bool = False) -> bool:
    lower = text.lower().strip()
    if not lower or not _TAMIL_SCRIPT_RE.search(text):
        return False
    has_food_signal = bool(re.search(
        r'\b(biryani|soup|naan|butter|chicken|mutton|pizza|dosa|idli|coffee|tea|rice|curry|burger|fried\s+rice)\b',
        lower,
    ))
    has_connector = any(token in text for token in _MIXED_ORDER_CONNECTORS)
    has_multiple_quantities = len(re.findall(
        r'(?<!\S)(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)\s+',
        lower,
    )) >= 2
    has_restaurant_hint = "restaurant" in lower or "district" in lower or "ரெஸ்டார" in text
    return has_food_signal and (has_connector or has_multiple_quantities or has_restaurant_hint or session_has_restaurant)


def _normalize_mixed_voice_order_text(text: str, current_restaurant_name: str | None = None) -> str | None:
    if not _should_try_mixed_order_normalization(text, bool(current_restaurant_name)):
        return None

    try:
        from . import sarvam_service

        system_prompt = (
            "You normalize mixed Tamil-English food ordering transcripts into short English order text. "
            "Preserve quantities, menu item names, and restaurant names. "
            "If a restaurant is implied by context, use that exact restaurant name. "
            "If spoken Tamil sounds like an English restaurant name, convert it to the most likely restaurant name. "
            "Return plain text only, with concise clauses like: 1 mutton bone soup from Anjappar and 1 butter naan from Desi District. "
            "Do not explain anything."
        )
        context = f"Current restaurant: {current_restaurant_name}" if current_restaurant_name else ""
        normalized = sarvam_service.chat_completion(text, system_prompt, context).strip()
        normalized = re.sub(r'^```(?:text)?\s*', '', normalized)
        normalized = re.sub(r'\s*```$', '', normalized).strip()
        if not normalized:
            return None
        normalized_lower = normalized.lower()
        if (
            len(normalized) > 220
            or '\n' in normalized
            or normalized_lower.count('from ') == 0
            or any(marker in normalized_lower for marker in (
                "let's", "user", "input", "instructions", "query", "breaking it down",
                "the restaurants mentioned", "the menu items", "the structure should",
            ))
        ):
            return None
        if normalized.lower() == text.lower().strip():
            return None
        return normalized
    except Exception:
        return None


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


def _parse_multi_restaurant_order_sequence(lower: str, all_restaurants: list, db: Session,
                                           user_lat: float | None = None,
                                           user_lng: float | None = None):
    pattern = re.compile(
        rf'(?:^|\s+(?:and\s+)?)'
        rf'(?:(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+)?'
        rf'(.+?)\s+from\s+(.+?)'
        rf'(?=(?:\s+(?:and\s+)?(?:(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+.+?\s+from\s+))|$)',
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(lower))
    if len(matches) < 2:
        return None, None

    word_nums = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    found = []
    missing = []
    for match in matches:
        qty_str = match.group(1)
        item_phrase = match.group(2).strip(" ,")
        rest_phrase = match.group(3).strip(" ,")
        qty = word_nums.get(qty_str, int(qty_str) if qty_str and qty_str.isdigit() else 1)
        restaurant = _find_best_restaurant(rest_phrase, all_restaurants, user_lat=user_lat, user_lng=user_lng)
        if not restaurant:
            return None, None
        all_items = _get_all_restaurant_items(db, restaurant.id)
        parsed = _parse_order_items(item_phrase, all_items)
        if parsed:
            if qty != 1 and len(parsed) == 1 and parsed[0][1] == 1:
                found.append((restaurant, [(parsed[0][0], qty)]))
            else:
                found.append((restaurant, parsed))
            continue
        single = _find_best_item(item_phrase, all_items)
        if single:
            found.append((restaurant, [(single, qty)]))
        else:
            missing.append((restaurant, item_phrase, qty))

    return (found, missing) if (found or missing) else (None, None)


def _parse_multi_restaurant_order(cleaned: str, lower: str, all_restaurants: list, db: Session, user_id: int,
                                  user_lat: float | None = None,
                                  user_lng: float | None = None):
    """
    Parse "2 chicken biryani from Aroma and 1 chicken lollipop from Desi District".
    Returns (found, missing) where:
      found   = list of (restaurant, [(menu_item, qty)])  — items matched
      missing = list of (restaurant, item_phrase, qty)    — items not matched (ask user)
    Returns (None, None) if input doesn't look like a multi-restaurant order at all.
    """
    found_sequence, missing_sequence = _parse_multi_restaurant_order_sequence(
        lower,
        all_restaurants,
        db,
        user_lat=user_lat,
        user_lng=user_lng,
    )
    if found_sequence is not None or missing_sequence is not None:
        return found_sequence, missing_sequence

    parts = re.split(r"\s+and\s+|\s*,\s*and\s*", lower)
    if len(parts) < 2:
        return None, None
    prefix_strip = r"^(?:i\s+would\s+like\s+to\s+|i\s+want\s+to\s+|please\s+)?(?:order|get|add)\s+"
    found = []
    missing = []
    for part in parts:
        part = re.sub(prefix_strip, "", part.strip()).strip()
        if not part:
            continue
        m = re.search(r"^(?:(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+)?(.+?)\s+from\s+(.+)$", part)
        if not m:
            return None, None
        qty_str, item_phrase, rest_phrase = m.group(1), m.group(2).strip(), m.group(3).strip()
        # Convert word numbers to int
        _word_nums = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                      "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
        qty = _word_nums.get(qty_str, int(qty_str) if qty_str and qty_str.isdigit() else 1)
        restaurant = _find_best_restaurant(rest_phrase, all_restaurants, user_lat=user_lat, user_lng=user_lng)
        if not restaurant:
            return None, None
        all_items = _get_all_restaurant_items(db, restaurant.id)
        parsed = _parse_order_items(item_phrase, all_items)
        if not parsed:
            single = _find_best_item(item_phrase, all_items)
            if single:
                found.append((restaurant, [(single, qty)]))
            else:
                missing.append((restaurant, item_phrase, qty))
        else:
            found.append((restaurant, [(parsed[0][0], qty)]))

    if not found and not missing:
        return None, None
    return found, missing


def _apply_multi_order_result(db: Session, user_id: int, llm_orders: list, all_restaurants: list,
                              user_lat: float | None = None,
                              user_lng: float | None = None) -> list | None:
    """
    Resolve LLM-extracted multi-order (list of {restaurant_name, items: [{item_name, quantity}]})
    to (restaurant, [(menu_item, qty)]) using existing matchers. Returns None if any resolve fails.
    """
    found = []
    missing = []
    for o in llm_orders:
        rest_name = (o.get("restaurant_name") or "").strip()
        items_raw = o.get("items") or []
        if not rest_name:
            return None, None
        restaurant = _find_best_restaurant(rest_name, all_restaurants, user_lat=user_lat, user_lng=user_lng)
        if not restaurant:
            return None, None
        all_items = _get_all_restaurant_items(db, restaurant.id)
        for it in items_raw:
            iname = (it.get("item_name") or "").strip()
            qty = it.get("quantity", 1)
            if not iname:
                continue
            try:
                qty = int(qty) if qty is not None else 1
            except (TypeError, ValueError):
                qty = 1
            if qty < 1:
                qty = 1
            menu_item = _find_best_item(iname, all_items)
            if menu_item:
                found.append((restaurant, [(menu_item, qty)]))
            else:
                missing.append((restaurant, iname, qty))
    if not found and not missing:
        return None, None
    return found, missing


def _execute_multi_order(db: Session, user_id: int, found: list, missing: list, session: ChatSession | None = None) -> dict:
    """
    Add all found items to cart. For missing items, show that restaurant's categories
    and ask the user to clarify. Returns a _result() dict.
    """
    added_lines = []
    for rest, item_list in found:
        order = crud.get_user_order_for_restaurant(db, user_id, rest.id)
        if not order:
            order = crud.create_order(db, user_id, rest.id)
        for menu_item, qty in item_list:
            crud.add_order_item(db, order, menu_item, qty)
        crud.recompute_order_total(db, order)
        for menu_item, qty in item_list:
            added_lines.append(f"  **{rest.name}:** {qty}x {menu_item.name} — ${menu_item.price_cents * qty / 100:.2f}")

    clarify_lines = []
    clarify_voice = []
    for rest, item_phrase, qty in missing:
        cats = _categories_data(db, rest.id)
        cat_names = ", ".join(c["name"] for c in cats[:6]) if cats else "browse their menu"
        all_items = _get_all_restaurant_items(db, rest.id)
        options = _find_matching_items(item_phrase, all_items, limit=3)
        option_text = ""
        option_voice = ""
        if options:
            option_names = ", ".join(item.name for item in options)
            option_text = f"\n  Closest matches: {option_names}."
            option_voice = f" Closest matches are {option_names}."
        clarify_lines.append(
            f"  I couldn't find **{item_phrase}** at **{rest.name}**.\n"
            f"  Their categories: {cat_names}.\n"
            f"  What would you like from {rest.name}?{option_text}"
        )
        clarify_voice.append(
            f"I couldn't find {item_phrase} at {rest.name}. "
            f"They have: {cat_names}. What would you like from there?{option_voice}"
        )

    cart = _build_cart_summary_chat(db, user_id)
    rest_names = ", ".join(r.name for r, _ in found)

    reply_parts = []
    if added_lines:
        reply_parts.append("Added to your orders:\n" + "\n".join(added_lines))
    if clarify_lines:
        reply_parts.append("\n".join(clarify_lines))
    if not clarify_lines and added_lines:
        reply_parts.append("Go to Cart to review or add more from each restaurant.")

    reply = "\n\n".join(reply_parts)

    if clarify_voice:
        voice_prompt = " ".join(clarify_voice)
    elif rest_names:
        voice_prompt = f"Added items from {rest_names}. Go to cart to review or say done to finish."
    else:
        voice_prompt = "Added to your cart."

    if session is not None:
        _set_session_state(db, session, restaurant_id=None, category_id=None, order_id=None)

    return _result(reply, restaurant_id=None, cart_summary=cart, voice_prompt=voice_prompt)


def _haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_miles = 3958.8
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * radius_miles * asin(sqrt(a))


def _restaurant_distance(restaurant, user_lat: float | None, user_lng: float | None) -> float | None:
    if user_lat is None or user_lng is None:
        return None
    if getattr(restaurant, "latitude", None) is None or getattr(restaurant, "longitude", None) is None:
        return None
    try:
        return _haversine_miles(float(user_lat), float(user_lng), float(restaurant.latitude), float(restaurant.longitude))
    except (TypeError, ValueError):
        return None


def _rank_restaurants(name: str, all_restaurants, user_lat: float | None = None, user_lng: float | None = None):
    name_lower = name.lower().strip()
    scored = []
    for restaurant in all_restaurants:
        score = max(
            _similarity(name_lower, restaurant.name.lower()),
            _similarity(name_lower, restaurant.slug.replace('-', ' ')),
        )
        restaurant_name_lower = restaurant.name.lower()
        slug_clean = restaurant.slug.replace('-', ' ')
        if restaurant.slug == name_lower or restaurant_name_lower == name_lower:
            score = max(score, 1.0)
        elif name_lower in restaurant_name_lower or restaurant_name_lower in name_lower:
            score = max(score, 0.92)
        elif name_lower in slug_clean or slug_clean in name_lower:
            score = max(score, 0.9)
        distance = _restaurant_distance(restaurant, user_lat, user_lng)
        scored.append((restaurant, score, distance))
    scored.sort(key=lambda row: (-row[1], row[2] if row[2] is not None else float('inf'), row[0].name.lower()))
    return scored


def _find_best_restaurant(name: str, all_restaurants, user_lat: float | None = None,
                          user_lng: float | None = None) -> object | None:
    """Fuzzy match a restaurant name."""
    name_lower = name.lower().strip()
    if not name_lower:
        return None

    ascii_only = re.sub(_TAMIL_SCRIPT_RE, ' ', name_lower)
    ascii_only = re.sub(r'\s+', ' ', ascii_only).strip()
    if ascii_only and ascii_only != name_lower:
        ranked_ascii = _rank_restaurants(ascii_only, all_restaurants, user_lat=user_lat, user_lng=user_lng)
        if ranked_ascii:
            best_ascii, best_ascii_score, _ = ranked_ascii[0]
            if best_ascii_score >= 0.5:
                return best_ascii

    ranked = _rank_restaurants(name_lower, all_restaurants, user_lat=user_lat, user_lng=user_lng)
    if not ranked:
        return None
    best, best_score, _ = ranked[0]
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


def _format_cross_restaurant_display_query(query: str) -> str:
    lower = query.lower().strip()
    raw_tokens = [token for token in re.split(r"[^a-z0-9']+", lower) if token]
    keywords = [token for token in raw_tokens if token not in _CHAT_STOP_WORDS and len(token) >= 2]

    special_tokens = {"special", "specials", "today", "todays", "today's"}
    generic_tokens = {"something", "anything", "item", "items", "option", "options", "food", "dish", "dishes", "any"}

    has_special = any(token in special_tokens for token in raw_tokens)
    spice_terms = [token for token in keywords if token in {"spicy", "hot", "chili", "chilli", "pepper"}]
    meaningful = [token for token in keywords if token not in special_tokens and token not in generic_tokens]

    if has_special:
        if spice_terms:
            return f"{spice_terms[0]} specials"
        if meaningful:
            return " ".join(meaningful[:3])
        return "today's specials"

    if meaningful:
        return " ".join(meaningful[:4])
    if keywords:
        return " ".join(keywords[:4])
    return query.strip()


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


def _search_items_across_restaurants_relaxed(db: Session, query: str, restaurants, limit=8, min_keywords=1):
    """Like _search_items_across_restaurants but require only min_keywords to match (for 'cheap biryani', 'best combos')."""
    raw_keywords = query.lower().strip().split()
    keywords = [kw for kw in raw_keywords if kw not in _CHAT_STOP_WORDS and len(kw) >= 2]
    if not keywords:
        keywords = sorted(raw_keywords, key=len, reverse=True)[:2]
    if not keywords:
        return []

    results = []
    for rest in restaurants:
        all_items = _get_all_restaurant_items(db, rest.id)
        for item in all_items:
            if item.price_cents <= 0:
                continue
            item_name_lower = item.name.lower()
            matched = sum(1 for kw in keywords if _fuzzy_match_chat(kw, item_name_lower))
            if matched >= min(min_keywords, len(keywords)):
                exact_bonus = sum(1 for kw in keywords if kw in item_name_lower)
                score = matched + exact_bonus
                results.append((item, rest, score))

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


_SPOKEN_DIGIT_WORDS = {
    "zero": "0", "oh": "0",
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
_QUANTITY_DIGIT_PATTERN = r'(?:20|1[0-9]|[1-9])'


def _normalize_spoken_numeric_item_names(text: str) -> str:
    """Convert speech forms like 'triple five' to '555' so item names aren't mistaken for quantities."""
    normalized = re.sub(r'([a-z])([A-Z])', r'\1 \2', text.strip())
    normalized = normalized.lower().strip()

    def _repeat_digit(match: re.Match) -> str:
        repeat_word = match.group(1)
        digit_word = match.group(2)
        digit = _SPOKEN_DIGIT_WORDS.get(digit_word, digit_word)
        repeat = 3 if repeat_word == "triple" else 2
        return digit * repeat

    normalized = re.sub(
        rf'\b(double|triple)\s+({"|".join(_SPOKEN_DIGIT_WORDS.keys())}|\d)\b',
        _repeat_digit,
        normalized,
    )
    return normalized


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


def _has_add_intent(text: str) -> bool:
    """True if the message clearly asks to add/order something (not just browse)."""
    lower = text.lower().strip()
    add_phrases = (
        "add", "get me", "give me", "i want", "i'd like", "order", "can i have",
        "can i get", "one ", "two ", "1 ", "2 ", "a ", "an ",
    )
    return any(p in lower for p in add_phrases)


def _is_vague_selected_restaurant_suggestion_request(text: str) -> bool:
    """Detect vague recommendation-style prompts that should browse, not mutate the cart."""
    lower = text.lower().strip()
    if not lower or len(lower.split()) < 3:
        return False

    if any(token in lower for token in (
        "clear cart", "clear the cart", "show cart", "checkout", "place order", "done",
        "remove", "cancel order", "change the restaurant", "switch restaurant",
    )):
        return False

    if any(token in lower for token in ("recommend", "suggest", "surprise me", "what do you have", "what have you got")):
        return True

    if re.search(r'\b(?:what|which)\b.*\b(?:available|have|special|options?)\b', lower):
        return True

    vague_markers = (
        "something", "anything", "options", "option", "special item", "special items",
        "special menu", "special menus", "best", "popular", "today", "today's",
    )
    has_vague_marker = any(marker in lower for marker in vague_markers)

    if not has_vague_marker:
        return False

    generic_dish_tokens = {
        "special", "specials", "item", "items", "option", "options", "something", "anything",
        "food", "dish", "dishes", "today", "todays", "todays", "menu", "menus", "best",
        "popular", "spicy", "hot", "good", "tasty", "here",
    }

    def _has_concrete_dish_name(dish_name: str | None) -> bool:
        if not dish_name:
            return False
        tokens = [token for token in re.split(r'[^a-z0-9]+', dish_name.lower()) if token]
        meaningful = [token for token in tokens if token not in generic_dish_tokens]
        return bool(meaningful)

    explicit_order_markers = (
        "add ", "order ", "can i have", "can i get", "one ", "two ", "1 ", "2 ",
    )
    if any(marker in lower for marker in explicit_order_markers) and not any(token in lower for token in ("option", "options", "recommend", "suggest", "special", "today")):
        return False

    try:
        from .intent_extractor import extract_intent_local

        local_intent = extract_intent_local(text)
        concrete_dish = _has_concrete_dish_name(local_intent.dish_name)
        if local_intent.recommendation_mode and not concrete_dish and not local_intent.dish_category:
            return True
        if concrete_dish or local_intent.dish_category:
            return False
    except Exception:
        pass

    return has_vague_marker


def _rank_suggestion_items(query: str, items: list[MenuItem], limit: int = 5) -> list[MenuItem]:
    """Rank candidate suggestion items for a vague request without mutating the cart."""
    lower = query.lower().strip()
    matches = _find_matching_items(lower, items, limit=limit)
    if matches:
        return matches

    spicy_words = ("spicy", "hot", "pepper", "chilli", "chili")
    if any(word in lower for word in spicy_words):
        spicy_matches = [item for item in items if any(word in item.name.lower() for word in spicy_words)]
        if spicy_matches:
            return spicy_matches[:limit]

    return items[:limit]


_CLARIFICATION_WORDS = (
    "what", "huh", "sorry", "pardon", "eh", "repeat", "again",
    "hello", "hey", "wait", "um", "ok", "yeah",
)


def _try_category_match(cleaned: str, lower: str, categories: list, session) -> "Category | None":
    """Match user input to a category (for browse/open menu). Returns category or None."""
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

    cat_match = None
    for cat in categories:
        if cat.name.lower() == lower or str(cat.id) == lower or (category_query and cat.name.lower() == category_query):
            cat_match = cat
            break
    if not cat_match and len(input_words) >= 1:
        for cat in categories:
            cat_lower = cat.name.lower()
            cat_words = [w.strip() for w in cat_lower.replace("/", " ").split() if w.strip()]
            for iw in input_words:
                if len(iw) < 2:
                    continue
                for cw in cat_words:
                    if iw in cw or cw in iw or _similarity(iw, cw) >= 0.7:
                        cat_match = cat
                        break
                if cat_match:
                    break
            if cat_match:
                break
    if not cat_match:
        best_cat, best_score = None, 0.0
        for cat in categories:
            cat_lower = cat.name.lower()
            score = max(_similarity(q, cat_lower), _similarity(lower, cat_lower))
            for word in cat_lower.replace("/", " ").split():
                word = word.strip()
                if word:
                    for iw in input_words:
                        score = max(score, _similarity(q, word), _similarity(iw, word))
            if score > best_score:
                best_score = score
                best_cat = cat
        if best_cat:
            cat_words = len(best_cat.name.split())
            if best_score >= 0.55 and len(input_words) <= max(cat_words, 1):
                cat_match = best_cat
    if not cat_match and not (session.category_id and len(cleaned.split()) >= 2):
        cat_match = _llm_match_category(cleaned, categories)
    if cat_match and session.category_id and cat_match.id == session.category_id:
        cat_match = None
    return cat_match


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


def _extract_compound_items(part: str, all_items: list[MenuItem], lead_quantity: int = 1) -> list[tuple[MenuItem, int]]:
    """Extract multiple distinct items from one chunk when STT glues them together."""
    compact_part = re.sub(r'[^a-z0-9]+', '', part.lower())
    if len(compact_part) < 6:
        return []

    candidates = []
    for item in all_items:
        compact_name = re.sub(r'[^a-z0-9]+', '', item.name.lower())
        if len(compact_name) < 4:
            continue
        start = compact_part.find(compact_name)
        if start == -1:
            continue
        end = start + len(compact_name)
        candidates.append((start, end, len(compact_name), item))

    if len(candidates) < 2:
        return []

    candidates.sort(key=lambda row: (row[0], -row[2]))
    chosen = []
    last_end = -1
    used_ids = set()
    for start, end, _, item in candidates:
        if item.id in used_ids or start < last_end:
            continue
        chosen.append(item)
        used_ids.add(item.id)
        last_end = end

    if len(chosen) < 2:
        return []

    results = []
    for idx, item in enumerate(chosen):
        qty = lead_quantity if idx == 0 else 1
        results.append((item, qty))
    return results


def _parse_order_items(text: str, all_items: list[MenuItem]) -> list[tuple[MenuItem, int]]:
    word_to_num = {
        "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }

    cleaned = _normalize_spoken_numeric_item_names(text)
    for filler in ["i would like to order", "i want to order", "i'd like to order",
                   "i want", "i'd like", "i would like", "give me", "get me",
                   "can i have", "can i get", "please", "order", "add", "to order"]:
        cleaned = cleaned.replace(filler, "")
    cleaned = cleaned.strip().strip(",").strip()

    if not cleaned:
        return []

    parts = re.split(r'\s*(?:,\s*and|\band\b|,|&|\+)\s*', cleaned)

    # Voice transcripts often chain multiple quantity-item phrases without "and" or commas,
    # e.g. "1 biryani family pack one masala grilled fish 1 tandoori shrimp jhinga".
    # Split on repeated quantity markers so each phrase can be matched independently.
    if len(parts) == 1:
        qty_markers = list(re.finditer(
            rf'(?<!\S)({_QUANTITY_DIGIT_PATTERN}|a|an|one|two|three|four|five|six|seven|eight|nine|ten)\s+',
            cleaned,
        ))
        if len(qty_markers) >= 2:
            chained_parts = []
            for idx, marker in enumerate(qty_markers):
                start = marker.start()
                end = qty_markers[idx + 1].start() if idx + 1 < len(qty_markers) else len(cleaned)
                segment = cleaned[start:end].strip(" ,")
                if segment:
                    chained_parts.append(segment)
            if chained_parts:
                parts = chained_parts

    results = []
    for part in parts:
        part = part.strip()
        if not part:
            continue

        quantity = 1
        num_match = re.match(rf'^({_QUANTITY_DIGIT_PATTERN})\s+(.+)', part)
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

        compound_items = _extract_compound_items(part, all_items, quantity)
        if compound_items:
            results.extend(compound_items)
            continue

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

def process_message(db: Session, session: ChatSession, text: str,
                    user_lat: float | None = None,
                    user_lng: float | None = None) -> dict:
    cleaned = text.strip()
    lower = cleaned.lower()
    parsing_cleaned = cleaned
    parsing_lower = lower

    # --- Group order intent (voice or text): open Group tab ---
    _group_phrases = (
        "group order", "group ordering", "start a group order", "order as a group",
        "order for a group", "order together", "group food", "group lunch", "group dinner",
        "office lunch", "company lunch", "order for the team", "order for the office",
    )
    _group_pattern = re.compile(
        r"(?:find|get|order|want|need)\s+(?:food|meals?|lunch|dinner)\s+for\s+(\d+)\s+people",
        re.I,
    )
    if any(p in lower for p in _group_phrases) or _group_pattern.search(lower):
        out = _result(
            "Open the **Group Order** tab to start a group order. Share the link with friends, add their preferences, and get AI recommendations for the whole group!",
            voice_prompt="I've opened the Group Order tab. Start a group order and share the link with your friends.",
        )
        out["open_group_tab"] = True
        return out

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

    current_restaurant_name = None
    if session.restaurant_id:
        current_restaurant = db.query(Restaurant).filter(Restaurant.id == session.restaurant_id).first()
        current_restaurant_name = current_restaurant.name if current_restaurant else None
    should_try_normalization = _should_try_mixed_order_normalization(cleaned, bool(current_restaurant_name))
    if should_try_normalization:
        _debug_log_mixed_order(
            "attempt",
            session_id=session.id,
            current_restaurant=current_restaurant_name,
            original=cleaned,
        )
    normalized_order_text = _normalize_mixed_voice_order_text(cleaned, current_restaurant_name=current_restaurant_name)
    if normalized_order_text:
        parsing_cleaned = normalized_order_text.strip()
        parsing_lower = parsing_cleaned.lower()
        _debug_log_mixed_order(
            "accepted",
            session_id=session.id,
            current_restaurant=current_restaurant_name,
            original=cleaned,
            normalized=parsing_cleaned,
        )
    elif should_try_normalization:
        _debug_log_mixed_order(
            "rejected",
            session_id=session.id,
            current_restaurant=current_restaurant_name,
            original=cleaned,
            reason="normalizer_returned_empty_or_unusable_text",
        )

    # --- Multi-restaurant order: detect regardless of current session restaurant ---
    # Run whenever the input contains 2+ "from X" patterns (covers both no-restaurant and has-restaurant sessions)
    _from_count = len(re.findall(r'\bfrom\s+\w', parsing_lower))
    if _from_count >= 2:
        all_restaurants_multi = crud.list_restaurants(db)
        found_multi, missing_multi = _parse_multi_restaurant_order(
            parsing_cleaned,
            parsing_lower,
            all_restaurants_multi,
            db,
            session.user_id,
            user_lat=user_lat,
            user_lng=user_lng,
        )
        if found_multi is None:
            llm_orders = extract_multi_order(cleaned)
            if llm_orders:
                found_multi, missing_multi = _apply_multi_order_result(
                    db,
                    session.user_id,
                    llm_orders,
                    all_restaurants_multi,
                    user_lat=user_lat,
                    user_lng=user_lng,
                )
        if found_multi is not None or missing_multi:
            return _execute_multi_order(db, session.user_id, found_multi or [], missing_multi or [], session=session)

    # --- If no restaurant selected yet: try smart matching ---
    if session.restaurant_id is None:
        all_restaurants = crud.list_restaurants(db)

        extracted_name = _extract_restaurant_name(parsing_cleaned)
        item_hint = _extract_item_after_restaurant(parsing_cleaned) if extracted_name else None

        candidate = extracted_name or parsing_cleaned
        restaurant = _find_best_restaurant(candidate, all_restaurants, user_lat=user_lat, user_lng=user_lng)

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

        # Multi-item order from home screen: "1 X and 1 Y" with no restaurant specified
        # Try each restaurant to see if it has all requested items
        _home_multi = bool(re.search(r'\b(?:and|&)\b', parsing_lower)) and _has_add_intent(parsing_cleaned)
        if _home_multi and all_restaurants:
            for rest in all_restaurants:
                rest_items = _get_all_restaurant_items(db, rest.id)
                if not rest_items:
                    continue
                parsed_multi = _parse_order_items(parsing_cleaned, rest_items)
                if len(parsed_multi) >= 2:
                    order = crud.get_user_order_for_restaurant(db, session.user_id, rest.id)
                    if not order:
                        order = crud.create_order(db, session.user_id, rest.id)
                    _set_session_state(db, session, restaurant_id=rest.id, order_id=order.id)
                    crud.attach_order_to_session(db, session, order)
                    added_lines, added_names = [], []
                    for menu_item, qty in parsed_multi:
                        crud.add_order_item(db, order, menu_item, qty)
                        price = f"${menu_item.price_cents * qty / 100:.2f}"
                        added_lines.append(f"  {qty}x {menu_item.name} - {price}")
                        added_names.append(menu_item.name)
                    crud.recompute_order_total(db, order)
                    total = f"${order.total_cents / 100:.2f}"
                    cats = _categories_data(db, rest.id)
                    cart = _build_cart_summary_chat(db, session.user_id)
                    voice_added = ", ".join(added_names)
                    reply = f"Added to your order at {rest.name}:\n" + "\n".join(added_lines)
                    reply += f"\n\nCart total: {total}"
                    return _result(
                        reply, restaurant_id=rest.id, order_id=order.id,
                        categories=cats, cart_summary=cart,
                        voice_prompt=f"Added {voice_added} from {rest.name}. Want anything else, or say done to finish?",
                    )

        # No restaurant match — try cross-restaurant item search (e.g. "spicy biryani", "cheap biryani", "best combos")
        if all_restaurants and len(parsing_cleaned) > 2:
            cross_results = _search_items_across_restaurants(db, parsing_cleaned, all_restaurants)
            if not cross_results:
                cross_results = _search_items_across_restaurants_relaxed(db, parsing_cleaned, all_restaurants, limit=8, min_keywords=1)
            if cross_results:
                # Extract meaningful keywords for display
                display_query = _format_cross_restaurant_display_query(parsing_cleaned)
                lines = [f'Found "{display_query}" at these restaurants:', ""]
                seen = set()
                rest_names = []
                for item, rest, score in cross_results:
                    if rest.id not in seen:
                        lines.append(f"• **{rest.name}** — {item.name} (${item.price_cents/100:.2f})")
                        rest_names.append(rest.name)
                        seen.add(rest.id)
                lines.extend(["", f'Say the restaurant name or type #{cross_results[0][1].slug} to order!'])
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
    if session.restaurant_id and len(parsing_cleaned) > 3:
        discovery_hints = ("nearby", "near me", "cheap", "cheapest", "restaurants that", "restaurants with",
                          "where can i get", "where can i find", "who has", "which restaurant has")
        if any(h in parsing_lower for h in discovery_hints):
            all_restaurants = crud.list_restaurants(db)
            cross_results = _search_items_across_restaurants(db, parsing_cleaned, all_restaurants)
            if cross_results:
                _set_session_state(db, session, restaurant_id=None, category_id=None, order_id=None)
                display_query = _format_cross_restaurant_display_query(parsing_cleaned)
                lines = [f'Found "{display_query}" at these restaurants:', ""]
                seen = set()
                rest_names = []
                for item, rest, score in cross_results:
                    if rest.id not in seen:
                        lines.append(f"• **{rest.name}** — {item.name} (${item.price_cents/100:.2f})")
                        rest_names.append(rest.name)
                        seen.add(rest.id)
                lines.extend(["", f'Say the restaurant name or type #{cross_results[0][1].slug} to order!'])
                return _result(
                    "\n".join(lines),
                    restaurant_id=None,
                    voice_prompt=f"I found that at: {', '.join(rest_names[:3])}. Which restaurant would you like?",
                )

    # --- When items are already displayed (user is in a category): try ITEM first (add to cart), then category (switch) ---
    all_items = _get_all_restaurant_items(db, session.restaurant_id)
    categories = crud.list_categories(db, session.restaurant_id)
    category_items = [i for i in all_items if session.category_id and i.category_id == session.category_id]

    # --- Multi-item order: bypass category-scoped fast path when the utterance clearly
    # contains multiple requested items, even if STT omitted "and" or commas.
    item_parsed = []
    _quantity_marker_count = len(re.findall(
        r'(?<!\S)(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)\s+',
        parsing_lower,
    ))
    _has_multi_item = (
        (bool(re.search(r'\b(?:and|&)\b', parsing_lower)) and _has_add_intent(parsing_cleaned))
        or _quantity_marker_count >= 2
    )
    if _has_multi_item:
        multi_parsed = _parse_order_items(parsing_cleaned, all_items)
        if len(multi_parsed) >= 2:
            item_parsed = multi_parsed

    if not item_parsed:
        # Short vague queries (e.g. "family means" / "family meals"): try category first so we open that menu instead of adding one item
        if len(parsing_cleaned.split()) <= 2 and not _has_add_intent(parsing_cleaned):
            single_item_early = _find_best_item(parsing_cleaned, category_items or all_items)
            cat_match_early = None
            if parsing_cleaned.lower().strip() not in _CLARIFICATION_WORDS and not single_item_early:
                cat_match_early = _try_category_match(parsing_cleaned, parsing_lower, categories, session)
            if cat_match_early:
                _set_session_state(db, session, category_id=cat_match_early.id)
                items = _items_data(db, cat_match_early.id)
                return _result(
                    f"{cat_match_early.name} — {len(items)} items. Tap + to add or tell me the item name.",
                    restaurant_id=session.restaurant_id,
                    category_id=cat_match_early.id,
                    order_id=session.order_id,
                    categories=_categories_data(db, session.restaurant_id),
                    items=items,
                    voice_prompt=f"{cat_match_early.name}. {len(items)} items. Which one would you like?",
                )

        if _is_vague_selected_restaurant_suggestion_request(parsing_cleaned):
            if session.category_id and category_items:
                current_category = next((cat for cat in categories if cat.id == session.category_id), None)
                suggested_items = _rank_suggestion_items(parsing_cleaned, category_items)
                item_dicts = [
                    {
                        "id": item.id,
                        "name": item.name,
                        "description": item.description or "",
                        "price_cents": item.price_cents,
                    }
                    for item in suggested_items
                ]
                prefix = "Here are some spicy options" if "spicy" in parsing_lower else "Here are some options"
                label = current_category.name if current_category else "this category"
                return _result(
                    f"{prefix} from {label}. Tap + to add or tell me which one you want.",
                    restaurant_id=session.restaurant_id,
                    category_id=session.category_id,
                    order_id=session.order_id,
                    categories=_categories_data(db, session.restaurant_id),
                    items=item_dicts,
                    voice_prompt=f"{prefix}. Tell me which one you want.",
                )

            cat_data = _categories_data(db, session.restaurant_id)
            cat_names = [cat["name"] for cat in cat_data[:6]]
            cat_list = ", ".join(cat_names)
            return _result(
                f"Pick a category and I will show you some options: {cat_list}",
                restaurant_id=session.restaurant_id,
                category_id=session.category_id,
                order_id=session.order_id,
                categories=cat_data,
                voice_prompt="Pick a category and I will show you some options.",
            )

        # When user is viewing a category's items: try FAST path first (fuzzy/token), LLM only as fallback
        # so e.g. "iced coffee" -> instant match; "I would like one iced coffee" -> parse_order_items or LLM
        if session.category_id and category_items:
            # Direct name match first for ANY order phrase ("I want iced coffee", "give me a cappuccino", etc.)
            phrase = _extract_item_phrase(parsing_cleaned)
            if phrase:
                for item in category_items:
                    iname = item.name.lower()
                    # Full match, or item name in phrase, or phrase in item name (handles voice/typos)
                    if phrase == iname or iname in phrase or phrase in iname:
                        item_parsed = [(item, max(1, _extract_quantity_from_message(parsing_cleaned)))]
                        break
                # If no exact/substring match, try longest item name contained in phrase (e.g. "large iced coffee" -> "Iced Coffee")
                if not item_parsed and len(phrase) > 3:
                    best_item, best_len = None, 0
                    for item in category_items:
                        iname = item.name.lower()
                        if iname in phrase and len(iname) > best_len:
                            best_item, best_len = item, len(iname)
                    if best_item:
                        item_parsed = [(best_item, max(1, _extract_quantity_from_message(parsing_cleaned)))]
            if not item_parsed:
                item_parsed = _parse_order_items(parsing_cleaned, category_items)
            if not item_parsed:
                single = _find_best_item(parsing_cleaned, category_items)
                if single:
                    item_parsed = [(single, max(1, _extract_quantity_from_message(parsing_cleaned)))]
            if not item_parsed:
                llm_item = _llm_match_item(parsing_cleaned, category_items)
                if llm_item:
                    qty = _extract_quantity_from_message(parsing_cleaned)
                    item_parsed = [(llm_item, max(1, qty))]
        if not item_parsed:
            item_parsed = _parse_order_items(parsing_cleaned, all_items)
            if not item_parsed:
                single = _find_best_item(parsing_cleaned, all_items)
                if single:
                    item_parsed = [(single, 1)]
            if not item_parsed:
                llm_item = _llm_match_item(parsing_cleaned, all_items)
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

    if cleaned.lower().strip() in _CLARIFICATION_WORDS:
        cats = _categories_data(db, session.restaurant_id)
        return _result(
            "You can say a category name, an item to add, or **done** to finish.",
            restaurant_id=session.restaurant_id,
            order_id=session.order_id,
            categories=cats,
            voice_prompt="Say a category or item name, or say done to finish.",
        )

    # --- No item match: try CATEGORY match (so user can say "starters" or "family meals" to open that menu) ---
    cat_match = _try_category_match(parsing_cleaned, parsing_lower, categories, session)

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

    # --- Submit order / negative response ("no" = nothing else) ---
    if lower in ("#order", "submit", "submit order", "place order", "done",
                 "checkout", "check out", "that's all", "thats all", "confirm",
                 "place my order", "send order", "i'm done", "im done",
                 "finished", "that is all", "no more", "nothing else",
                 "no", "nope", "nah", "no thanks", "no thank you"):
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
        if cleaned.lower().strip() in _CLARIFICATION_WORDS:
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
