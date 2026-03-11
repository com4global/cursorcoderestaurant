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
    session.updated_at = datetime.utcnow()
    db.commit()


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


def _search_items_across_restaurants(db: Session, query: str, restaurants, limit=5):
    """Search for items across all restaurants."""
    query_lower = query.lower().strip()
    results = []
    for rest in restaurants:
        all_items = _get_all_restaurant_items(db, rest.id)
        for item in all_items:
            score = _similarity(query_lower, item.name.lower())
            if query_lower in item.name.lower():
                score = max(score, 0.8)
            for word in item.name.lower().split():
                score = max(score, _similarity(query_lower, word))
            if score >= 0.4:
                results.append((item, rest, score))
    results.sort(key=lambda x: x[2], reverse=True)
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
        if score >= 0.65:  # Raised from 0.55 for better accuracy
            scored.append((item, score))

    scored.sort(key=lambda x: x[1], reverse=True)

    if not scored:
        return None

    # If top match is strong enough (>= 0.75), return it directly
    if scored[0][1] >= 0.75:
        return scored[0][0]

    # If borderline (0.65-0.75), only return if it's clearly the best
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
    for filler in ["i want", "i'd like", "i would like", "give me", "get me",
                   "can i have", "can i get", "please", "order", "add"]:
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

    # --- Reset / Exit ---
    if lower in ("#reset", "#exit", "reset", "exit", "start over"):
        _set_session_state(db, session, restaurant_id=None, category_id=None, order_id=None)
        return _result(
            "Session reset. Type # to pick a restaurant!",
            voice_prompt="Which restaurant would you like to order from?",
        )

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
                        voice_prompt=f"Added {added_names}. Your total is {total}. Would you like anything else, or say done to finish?",
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
                            voice_prompt=f"In {cat.name} we have: {item_list}. Which item would you like to add?",
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
                lines = [f'Found "{cleaned}" at these restaurants:\n']
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
                voice_prompt=f"Added {menu_item.name}. Total is {total}. Want anything else, or say done?",
            )
        return _result(
            "Item not found.",
            restaurant_id=session.restaurant_id,
            voice_prompt="I couldn't find that item. What would you like to add?",
        )

    # --- Smart matching: try items FIRST when browsing a category or multi-word input ---
    # This prevents "Aloo Tikka Chat" from matching the "Chat" category
    # instead of the menu item "Aloo Tikka Chat"
    all_items = _get_all_restaurant_items(db, session.restaurant_id)
    input_words = lower.split()

    # Try item matching first (before category matching)
    item_parsed = _parse_order_items(cleaned, all_items)
    if not item_parsed:
        single = _find_best_item(cleaned, all_items)
        if single:
            item_parsed = [(single, 1)]

    if item_parsed:
        # Found an item match — add to cart
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
            voice_prompt=f"Added {voice_added}. Your total is {total}. Would you like anything else, or say done to finish?",
        )

    # If no exact item match but multi-word input, try disambiguation before category matching
    if len(input_words) >= 2:
        matches = _find_matching_items(cleaned, all_items)
        if matches:
            items_data = [
                {"id": m.id, "name": m.name, "description": m.description or "", "price_cents": m.price_cents}
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

    # Also match if user just types a category name
    categories = crud.list_categories(db, session.restaurant_id)
    cat_match = None

    # Pass 1: Exact match
    for cat in categories:
        if cat.name.lower() == lower or str(cat.id) == lower:
            cat_match = cat
            break

    # Pass 2: Partial substring match
    if not cat_match:
        for cat in categories:
            cat_lower = cat.name.lower()
            cat_words = [w.strip() for w in cat_lower.replace("/", " ").split()]
            input_words = lower.split()
            for iw in input_words:
                for cw in cat_words:
                    if len(iw) >= 3 and (iw in cw or cw in iw):
                        cat_match = cat
                        break
                    if len(iw) >= 3 and _similarity(iw, cw) >= 0.75:
                        cat_match = cat
                        break
                if cat_match:
                    break
            if cat_match:
                break

    # Pass 3: Fuzzy match on full name
    if not cat_match:
        best_cat, best_score = None, 0.0
        for cat in categories:
            cat_lower = cat.name.lower()
            score = _similarity(lower, cat_lower)
            for word in cat_lower.replace("/", " ").split():
                word = word.strip()
                if word:
                    score = max(score, _similarity(lower, word))
            if score > best_score:
                best_score = score
                best_cat = cat
        if best_score >= 0.55:
            cat_match = best_cat

    if cat_match:
        _set_session_state(db, session, category_id=cat_match.id)
        items = _items_data(db, cat_match.id)
        item_list = _build_voice_item_list(items)
        return _result(
            f"{cat_match.name} — {len(items)} items. Tap + to add or just tell me what you want!",
            restaurant_id=session.restaurant_id,
            category_id=cat_match.id,
            order_id=session.order_id,
            items=items,
            voice_prompt=f"In {cat_match.name} we have: {item_list}. Which one would you like?",
        )

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

        # Show categories as fallback
        cats = _categories_data(db, session.restaurant_id)
        cat_list = _build_voice_category_list(cats)
        return _result(
            "I didn't catch that. Pick a category or type what you want!",
            restaurant_id=session.restaurant_id,
            order_id=session.order_id,
            categories=cats,
            voice_prompt=f"I didn't catch that. Our categories are: {cat_list}. Which one would you like?",
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
        voice_prompt=f"Added {voice_added}. Your total is {total}. Would you like anything else, or say done to finish?",
    )
