"""
Chat engine with natural-language ordering and structured responses.

Returns dicts with:
  - reply: text message
  - restaurant_id, category_id, order_id: session state
  - categories: list of category dicts (for interactive chips)
  - items: list of item dicts (for interactive cards)
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
            categories=None, items=None, cart_summary=None):
    return {
        "reply": reply,
        "restaurant_id": restaurant_id,
        "category_id": category_id,
        "order_id": order_id,
        "categories": categories,
        "items": items,
        "cart_summary": cart_summary,
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
    # Words that are pure intent words, not food items
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
            # If ALL remaining words are intent words, skip this match
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
    results = []  # (item, restaurant, score)
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
# Fuzzy item matching
# ---------------------------------------------------------------------------

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _find_best_item(query: str, all_items: list[MenuItem]) -> MenuItem | None:
    query_lower = query.lower().strip()
    if not query_lower:
        return None

    for item in all_items:
        if item.name.lower() == query_lower:
            return item

    for item in all_items:
        if query_lower in item.name.lower() or item.name.lower() in query_lower:
            return item

    best_item, best_score = None, 0.0
    for item in all_items:
        score = _similarity(query_lower, item.name.lower())
        for word in item.name.lower().split():
            score = max(score, _similarity(query_lower, word))
        if score > best_score:
            best_score = score
            best_item = item
    return best_item if best_score >= 0.55 else None


def _find_matching_items(query: str, all_items: list[MenuItem], limit=5) -> list[MenuItem]:
    """Find multiple matching items for a search query."""
    query_lower = query.lower().strip()
    scored = []
    for item in all_items:
        score = _similarity(query_lower, item.name.lower())
        if query_lower in item.name.lower():
            score = max(score, 0.8)
        for word in item.name.lower().split():
            score = max(score, _similarity(query_lower, word))
        if score >= 0.4:
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
        return _result("Session reset. Type # to pick a restaurant!")

    # --- Restaurant selection via #slug ---
    if cleaned.startswith("#"):
        slug = cleaned.lstrip("#").strip().lower()
        if not slug:
            return _result("Type # followed by a restaurant name to get started.")

        restaurant = crud.get_restaurant_by_slug_or_id(db, slug)
        if not restaurant:
            restaurants = crud.list_restaurants(db)
            for r in restaurants:
                if _similarity(slug, r.slug) >= 0.6 or _similarity(slug, r.name.lower()) >= 0.6:
                    restaurant = r
                    break

        if not restaurant:
            return _result("Restaurant not found. Type # to see suggestions.")

        # Look up existing pending order for this restaurant
        existing_order = crud.get_user_order_for_restaurant(db, session.user_id, restaurant.id)
        new_order_id = existing_order.id if existing_order else None
        _set_session_state(db, session, restaurant_id=restaurant.id, category_id=None, order_id=new_order_id)
        cats = _categories_data(db, restaurant.id)

        reply = f"Welcome to {restaurant.name}! Pick a category or just tell me what you want."
        cart = _build_cart_summary_chat(db, session.user_id)
        return _result(reply, restaurant_id=restaurant.id, categories=cats, cart_summary=cart)

    # --- If no restaurant selected yet: try smart matching ---
    if session.restaurant_id is None:
        all_restaurants = crud.list_restaurants(db)

        # Try to extract a restaurant name from natural language
        extracted_name = _extract_restaurant_name(cleaned)
        item_hint = _extract_item_after_restaurant(cleaned) if extracted_name else None

        # If no pattern matched, try the raw text as a restaurant name
        candidate = extracted_name or cleaned
        restaurant = _find_best_restaurant(candidate, all_restaurants)

        if restaurant:
            existing_order = crud.get_user_order_for_restaurant(db, session.user_id, restaurant.id)
            new_order_id = existing_order.id if existing_order else None
            _set_session_state(db, session, restaurant_id=restaurant.id, category_id=None, order_id=new_order_id)
            cats = _categories_data(db, restaurant.id)
            cart = _build_cart_summary_chat(db, session.user_id)

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
                    reply = f"Welcome to {restaurant.name}!\n\nAdded to your order:\n" + "\n".join(added)
                    reply += f"\n\nCart total: {total}"
                    return _result(reply, restaurant_id=restaurant.id, order_id=order.id, categories=cats, cart_summary=cart)

                # Try matching as category
                categories = crud.list_categories(db, restaurant.id)
                for cat in categories:
                    if _similarity(item_hint.lower(), cat.name.lower()) >= 0.6:
                        items = _items_data(db, cat.id)
                        return _result(
                            f"Welcome to {restaurant.name}!\n\n{cat.name} — {len(items)} items. Tap + to add or tell me what you want!",
                            restaurant_id=restaurant.id, category_id=cat.id, order_id=new_order_id,
                            categories=cats, items=items, cart_summary=cart,
                        )

                # Try fuzzy item search as fallback
                matches = _find_matching_items(item_hint, all_items)
                if matches:
                    items_data = [
                        {"id": m.id, "name": m.name, "description": m.description or "", "price_cents": m.price_cents}
                        for m in matches
                    ]
                    return _result(
                        f'Welcome to {restaurant.name}!\n\nFound {len(matches)} items matching "{item_hint}". Tap + to add!',
                        restaurant_id=restaurant.id, order_id=new_order_id,
                        categories=cats, items=items_data, cart_summary=cart,
                    )

            reply = f"Welcome to {restaurant.name}! Pick a category or just tell me what you want."
            return _result(reply, restaurant_id=restaurant.id, categories=cats, cart_summary=cart)

        # No restaurant match — try cross-restaurant item search
        if all_restaurants and len(cleaned) > 2:
            cross_results = _search_items_across_restaurants(db, cleaned, all_restaurants)
            if cross_results:
                lines = [f'Found "{cleaned}" at these restaurants:\n']
                seen = set()
                for item, rest, score in cross_results:
                    if rest.id not in seen:
                        lines.append(f"• **{rest.name}** — {item.name} (${item.price_cents/100:.2f})")
                        seen.add(rest.id)
                lines.append(f'\nSay the restaurant name or type #{cross_results[0][1].slug} to order!')
                return _result("\n".join(lines))

        # Final fallback
        if all_restaurants:
            suggestions = [f"• {r.name} — #{r.slug}" for r in all_restaurants[:5]]
            return _result(
                "I couldn't find that restaurant. Available options:\n\n" + "\n".join(suggestions)
                + "\n\nSay a restaurant name or type # to browse!"
            )
        return _result("No restaurants available. Add your zipcode to find nearby options!")

    # --- Browse category by name or id ---
    if lower.startswith("category:") or lower.startswith("browse:"):
        cat_query = cleaned.split(":", 1)[1].strip()
        categories = crud.list_categories(db, session.restaurant_id)
        match = None
        for cat in categories:
            if str(cat.id) == cat_query or cat.name.lower() == cat_query.lower():
                match = cat
                break
        if match:
            items = _items_data(db, match.id)
            return _result(
                f"{match.name} — {len(items)} items. Tap to add or type what you want!",
                restaurant_id=session.restaurant_id,
                category_id=match.id,
                order_id=session.order_id,
                items=items,
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
            )
        return _result("Item not found.", restaurant_id=session.restaurant_id)

    # Also match if user just types a category name
    categories = crud.list_categories(db, session.restaurant_id)
    cat_match = None

    # Pass 1: Exact match
    for cat in categories:
        if cat.name.lower() == lower or str(cat.id) == lower:
            cat_match = cat
            break

    # Pass 2: Partial substring match (user text in category name or vice versa)
    if not cat_match:
        for cat in categories:
            cat_lower = cat.name.lower()
            # Split category name by / and spaces for multi-word categories
            cat_words = [w.strip() for w in cat_lower.replace("/", " ").split()]
            input_words = lower.split()
            # Check if any input word matches any category word closely
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

    # Pass 3: Fuzzy match on full name (lower threshold)
    if not cat_match:
        best_cat, best_score = None, 0.0
        for cat in categories:
            cat_lower = cat.name.lower()
            score = _similarity(lower, cat_lower)
            # Also check per-word similarity
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
        items = _items_data(db, cat_match.id)
        return _result(
            f"{cat_match.name} — {len(items)} items. Tap + to add or just tell me what you want!",
            restaurant_id=session.restaurant_id,
            category_id=cat_match.id,
            order_id=session.order_id,
            items=items,
        )

    # --- Show menu / categories ---
    if lower in ("menu", "show menu", "categories", "show categories", "what do you have"):
        cats = _categories_data(db, session.restaurant_id)
        return _result(
            "Here are the categories. Tap one to browse!",
            restaurant_id=session.restaurant_id,
            order_id=session.order_id,
            categories=cats,
        )

    # --- Submit order ---
    if lower in ("#order", "submit", "submit order", "place order", "done",
                 "checkout", "check out", "that's all", "thats all", "confirm",
                 "place my order", "send order"):
        if session.order_id is None:
            return _result(
                "Your cart is empty! Pick a category or tell me what you want.",
                restaurant_id=session.restaurant_id,
            )
        order = crud.get_order(db, session.order_id)
        if not order:
            _set_session_state(db, session, order_id=None)
            return _result("Cart not found. Tell me what you want to order!",
                          restaurant_id=session.restaurant_id)
        order.status = "submitted"
        db.commit()
        total = f"${order.total_cents / 100:.2f}"
        return _result(
            f"Order #{order.id} submitted! Total: {total}. Your order has been sent to the restaurant!",
            restaurant_id=session.restaurant_id,
            order_id=order.id,
        )

    # --- View cart (multi-restaurant) ---
    if lower in ("cart", "my cart", "show cart", "view cart", "what's in my cart"):
        pending_orders = crud.get_user_pending_orders(db, session.user_id)
        if not pending_orders:
            return _result("Your cart is empty! Just tell me what you want.",
                          restaurant_id=session.restaurant_id)
        lines = ["🛒 **Your Cart:**\n"]
        grand_total = 0
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
            lines.append(f"  Subtotal: ${order.total_cents / 100:.2f}\n")
            grand_total += order.total_cents
        if grand_total == 0:
            return _result("Your cart is empty!",
                          restaurant_id=session.restaurant_id)
        lines.append(f"**Grand Total: ${grand_total / 100:.2f}**")
        lines.append('\nSay "submit" to place your order!')
        cart = _build_cart_summary_chat(db, session.user_id)
        return _result("\n".join(lines),
                      restaurant_id=session.restaurant_id,
                      order_id=session.order_id,
                      cart_summary=cart)


    # --- Natural language ordering ---
    all_items = _get_all_restaurant_items(db, session.restaurant_id)
    parsed = _parse_order_items(cleaned, all_items)

    if not parsed:
        single_match = _find_best_item(cleaned, all_items)
        if single_match:
            parsed = [(single_match, 1)]

    if not parsed:
        # Try search and show matching items
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
            return _result(
                f'Found {len(matches)} items matching "{cleaned}". Tap + to add!',
                restaurant_id=session.restaurant_id,
                order_id=session.order_id,
                items=items_data,
            )

        # Show categories as fallback
        cats = _categories_data(db, session.restaurant_id)
        return _result(
            "I didn't catch that. Pick a category or type what you want!",
            restaurant_id=session.restaurant_id,
            order_id=session.order_id,
            categories=cats,
        )

    # Create or get order (per-restaurant)
    order = crud.get_user_order_for_restaurant(db, session.user_id, session.restaurant_id)
    if not order:
        order = crud.create_order(db, session.user_id, session.restaurant_id)
    crud.attach_order_to_session(db, session, order)

    added_lines = []
    for menu_item, qty in parsed:
        crud.add_order_item(db, order, menu_item, qty)
        price = f"${menu_item.price_cents * qty / 100:.2f}"
        added_lines.append(f"  {qty}x {menu_item.name} - {price}")

    crud.recompute_order_total(db, order)
    total = f"${order.total_cents / 100:.2f}"
    reply = "Added to your order:\n" + "\n".join(added_lines)
    reply += f"\n\nCart total: {total}"

    cart = _build_cart_summary_chat(db, session.user_id)
    return _result(reply,
                  restaurant_id=session.restaurant_id,
                  order_id=order.id,
                  cart_summary=cart)
