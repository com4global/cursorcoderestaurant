"""
Group Order Consensus Engine: score restaurants and suggest dishes for a group
based on preferences, budget, and dietary restrictions. No heavy AI — simple scoring.
"""
from __future__ import annotations

import re
from typing import NamedTuple

from sqlalchemy.orm import Session

from . import crud
from .models import GroupOrderMember, GroupOrderSession, MenuItem, Restaurant


class SuggestedItem(NamedTuple):
    item: MenuItem
    quantity: int
    portion_people: int


def _get_portion(item: MenuItem) -> int:
    if item.portion_people and item.portion_people > 0:
        return item.portion_people
    # Heuristics
    name = (item.name or "").lower()
    if re.search(r"biryani|pulao|fried rice|rice bowl", name):
        return 2
    if re.search(r"pizza|large|family", name):
        return 3
    if re.search(r"curry|dal|paneer|naan|roti|thali", name):
        return 2
    if re.search(r"soup|salad|burger|wrap|drink", name):
        return 1
    return 1


# Preference synonyms: map user words to menu keywords (so "briyani" and "burgers" match well)
_PREFERENCE_SYNONYMS: dict[str, list[str]] = {
    "biryani": ["biryani", "biriyani", "briyani", "pulao", "pulav", "rice", "fried rice"],
    "briyani": ["biryani", "biriyani", "briyani", "pulao", "pulav", "rice"],
    "burger": ["burger", "burgers", "cheeseburger"],
    "burgers": ["burger", "burgers", "cheeseburger"],
    "veg": ["veg", "vegetarian", "veggie", "paneer", "vegetable", "dal", "naan"],
    "vegetarian": ["veg", "vegetarian", "paneer", "vegetable", "dal"],
    "spicy": ["spicy", "hot", "chilli", "masala", "vindaloo"],
    "pizza": ["pizza", "pizzas"],
    "pasta": ["pasta", "spaghetti", "noodle", "noodles"],
    "chicken": ["chicken", "chicken"],
    "fish": ["fish", "salmon", "seafood", "prawn", "shrimp"],
}


def _expand_preference(preference: str | None) -> list[str]:
    """Turn user preference into a list of keywords to match on menu items."""
    if not preference or not preference.strip():
        return []
    pref = preference.lower().strip()
    # Direct synonym expansion
    if pref in _PREFERENCE_SYNONYMS:
        return _PREFERENCE_SYNONYMS[pref]
    # Multi-word: expand each word
    words = pref.split()
    out = []
    for w in words:
        if w in _PREFERENCE_SYNONYMS:
            out.extend(_PREFERENCE_SYNONYMS[w])
        elif len(w) >= 2:
            out.append(w)
    return out if out else [pref]


def _item_matches_preference(item: MenuItem, preference: str | None) -> bool:
    if not preference or not preference.strip():
        return True
    name = (item.name or "").lower()
    tags_str = (item.tags or "").lower() if isinstance(item.tags, str) else ""
    if isinstance(item.tags, list):
        tags_str = " ".join(str(t).lower() for t in item.tags)
    text = f"{name} {tags_str} {(item.cuisine or '')} {(item.protein_type or '')}"
    keywords = _expand_preference(preference)
    for kw in keywords:
        if len(kw) >= 2 and kw in text:
            return True
    return False


def _item_satisfies_diet(item: MenuItem, dietary: str | None) -> bool:
    if not dietary or not dietary.strip():
        return True
    d = dietary.lower()
    name = (item.name or "").lower()
    protein = (item.protein_type or "").lower()
    tags_str = (item.tags or "").lower() if isinstance(item.tags, str) else ""
    if isinstance(item.tags, list):
        tags_str = " ".join(str(t).lower() for t in item.tags)
    text = f"{name} {protein} {tags_str}"
    if "veg" in d or "vegetarian" in d:
        if "chicken" in text or "meat" in text or "fish" in text or "mutton" in text:
            return False
    if "vegan" in d:
        if "dairy" in text or "cheese" in text or "egg" in text or "milk" in text:
            return False
    if "dairy" in d or "no dairy" in d:
        if "cheese" in text or "milk" in text or "paneer" in text:
            return False
    return True


def _score_restaurant_for_group(
    db: Session,
    restaurant: Restaurant,
    members: list[GroupOrderMember],
    suggested: list[SuggestedItem],
) -> float:
    """
    Score = preference_match * 5 + rating * 2 + price_fit * 3 + variety_bonus.
    """
    if not suggested:
        return -1.0
    total_cents = sum(s.item.price_cents * s.quantity for s in suggested)
    people = len(members)
    per_person = total_cents / people if people else 0

    # Preference match: how many members have at least one item matching their preference
    preference_match = 0
    for m in members:
        for s in suggested:
            if _item_matches_preference(s.item, m.preference):
                preference_match += 1
                break
    pref_score = (preference_match / people * 5) if people else 0

    # Budget fit: all within budget?
    budget_ok = 0
    for m in members:
        if m.budget_cents is None or per_person <= m.budget_cents:
            budget_ok += 1
    price_fit = (budget_ok / people * 3) if people else 0

    # Rating
    rating = (restaurant.rating or 0) * 2

    # Variety: more distinct items = better
    variety = min(len(set(s.item.id for s in suggested)), 5) * 0.5

    return pref_score + price_fit + rating + variety


def get_group_recommendation(
    db: Session,
    group_session: GroupOrderSession,
    lat: float | None = None,
    lng: float | None = None,
    restaurant_ids: list[int] | None = None,
    cuisine: str | None = None,
) -> dict | None:
    """
    Find best restaurant and suggested dishes for the group.
    Searches across ALL active restaurants unless the user sets a preference:
    - restaurant_ids: only consider these restaurants (multi-select)
    - cuisine: only consider restaurants that have menu items with this cuisine (e.g. "Indian")
    Returns dict with restaurant_id, restaurant_name, suggested_items, total_cents,
    estimated_per_person_cents, reasons, group_discount_message.
    """
    members = list(group_session.members)
    if not members:
        return None

    people = len(members)
    max_budget = min((m.budget_cents for m in members if m.budget_cents is not None), default=None)
    if max_budget is None:
        max_budget = 5000 * people  # $50 per person default cap for group total
    else:
        max_budget = max_budget * people  # use min per-person budget * people as group cap

    if restaurant_ids:
        restaurants = []
        for rid in restaurant_ids:
            rest = crud.get_restaurant_by_slug_or_id(db, str(rid))
            if rest and rest.is_active:
                restaurants.append(rest)
    else:
        restaurants = crud.list_restaurants(db, query=None)

    if cuisine and cuisine.strip():
        cuisine_lower = cuisine.strip().lower()
        filtered = []
        for rest in restaurants:
            categories = crud.list_categories(db, rest.id)
            for cat in categories:
                for item in crud.list_items(db, cat.id):
                    if item.cuisine and cuisine_lower in item.cuisine.lower():
                        filtered.append(rest)
                        break
                else:
                    continue
                break
        restaurants = filtered
    best_score = -1.0
    best_result: dict | None = None

    for rest in restaurants:
        # Collect all menu items for this restaurant
        categories = crud.list_categories(db, rest.id)
        all_items: list[MenuItem] = []
        for cat in categories:
            all_items.extend(crud.list_items(db, cat.id))

        if not all_items:
            continue

        # Filter items: must satisfy all dietary restrictions
        def ok(item: MenuItem) -> bool:
            for m in members:
                if not _item_satisfies_diet(item, m.dietary_restrictions):
                    return False
            return True

        eligible = [i for i in all_items if ok(i)]
        if not eligible:
            continue

        # Build combo: prioritize one item per member matching their preference, then fill to feed everyone
        suggested: list[SuggestedItem] = []
        used_ids: set[int] = set()
        total_cents = 0

        # First pass: give EACH member at least one item that matches THEIR preference (when possible)
        for m in members:
            for item in eligible:
                if item.id in used_ids:
                    continue
                if total_cents + item.price_cents > max_budget:
                    continue
                if _item_matches_preference(item, m.preference):
                    portion = _get_portion(item)
                    qty = max(1, (people + portion - 1) // portion)
                    if total_cents + item.price_cents * qty <= max_budget:
                        suggested.append(SuggestedItem(item=item, quantity=qty, portion_people=portion))
                        used_ids.add(item.id)
                        total_cents += item.price_cents * qty
                        break

        # Second pass: if we have no preference matches yet, try to add items that match ANY member
        if not suggested:
            for m in members:
                for item in eligible:
                    if item.id in used_ids:
                        continue
                    if total_cents + item.price_cents > max_budget:
                        continue
                    if _item_matches_preference(item, m.preference):
                        portion = _get_portion(item)
                        qty = max(1, (people + portion - 1) // portion)
                        if total_cents + item.price_cents * qty <= max_budget:
                            suggested.append(SuggestedItem(item=item, quantity=qty, portion_people=portion))
                            used_ids.add(item.id)
                            total_cents += item.price_cents * qty
                            break
                if suggested:
                    break

        # Third pass: fill with items to feed everyone (variety: prefer different items)
        for item in sorted(eligible, key=lambda x: x.price_cents):
            if item.id in used_ids:
                continue
            if total_cents >= max_budget:
                break
            portion = _get_portion(item)
            need = people - sum(s.quantity * s.portion_people for s in suggested)
            if need <= 0:
                break
            qty = max(1, (need + portion - 1) // portion)
            cost = item.price_cents * qty
            if total_cents + cost <= max_budget:
                suggested.append(SuggestedItem(item=item, quantity=qty, portion_people=portion))
                used_ids.add(item.id)
                total_cents += cost

        if not suggested:
            continue

        # Require at least one suggested item to match at least one member's preference (avoid "random dish")
        preference_match_count = sum(
            1 for m in members
            if any(_item_matches_preference(s.item, m.preference) for s in suggested)
        )
        if preference_match_count == 0:
            continue  # skip restaurants where nothing matches anyone

        score = _score_restaurant_for_group(db, rest, members, suggested)
        if score > best_score:
            per_person = total_cents // people if people else 0
            reasons = []
            for m in members:
                if any(_item_matches_preference(s.item, m.preference) for s in suggested):
                    pref = (m.preference or "").strip() or "their preference"
                    reasons.append(f"Matches {m.name}'s preference ({pref})")
            if all(
                m.budget_cents is None or per_person <= m.budget_cents
                for m in members
            ):
                reasons.append("Within everyone's budget")
            veg_count = sum(1 for m in members if m.dietary_restrictions and "veg" in (m.dietary_restrictions or "").lower())
            if veg_count > 0:
                reasons.append("Veg option available")
            if rest.rating and rest.rating >= 4:
                reasons.append("Highly rated")
            if not reasons or "Matches" not in str(reasons):
                reasons.append("Popular dishes")

            discount_msg = None
            if total_cents >= 5000:  # $50
                discount_msg = "Order qualifies for group discount / free delivery at many restaurants."
            elif total_cents >= 4000:
                discount_msg = "Add one more item to unlock free delivery at many restaurants."

            best_score = score
            best_result = {
                "restaurant_id": rest.id,
                "restaurant_name": rest.name,
                "suggested_items": [
                    {
                        "item_id": s.item.id,
                        "name": s.item.name,
                        "price_cents": s.item.price_cents,
                        "quantity": s.quantity,
                        "portion_people": _get_portion(s.item),
                    }
                    for s in suggested
                ],
                "total_cents": total_cents,
                "estimated_per_person_cents": per_person,
                "reasons": reasons,
                "group_discount_message": discount_msg,
            }

    return best_result


def compute_group_split(
    total_cents: int,
    delivery_cents: int,
    tax_cents: int,
    members: list[GroupOrderMember],
    mode: str = "equal",
    item_assignments: list[tuple[str, int]] | None = None,
) -> dict:
    """
    Compute per-member split. mode in ("equal", "item").
    item_assignments: for "item" mode, list of (member_name, item_total_cents) per member.
    """
    n = len(members)
    if n == 0:
        return {"total_cents": total_cents, "delivery_cents": delivery_cents, "tax_cents": tax_cents, "split_mode": mode, "members": []}

    if mode == "item" and item_assignments and len(item_assignments) == n:
        # Item-based: each pays their items + equal share of delivery + tax
        total_shared = delivery_cents + tax_cents
        shared_per_person = total_shared // n
        remainder = total_shared % n
        result_members = []
        for i, m in enumerate(members):
            item_total = item_assignments[i][1] if i < len(item_assignments) else 0
            delivery_share = shared_per_person + (1 if i < remainder else 0)
            amount = item_total + delivery_share
            result_members.append({
                "member_name": m.name,
                "amount_cents": amount,
                "item_total_cents": item_total,
                "delivery_share_cents": delivery_share,
            })
        return {
            "total_cents": total_cents,
            "delivery_cents": delivery_cents,
            "tax_cents": tax_cents,
            "split_mode": "item",
            "members": result_members,
        }

    # Equal split
    grand = total_cents + delivery_cents + tax_cents
    per_person = grand // n
    remainder = grand % n
    result_members = []
    for i, m in enumerate(members):
        amount = per_person + (1 if i < remainder else 0)
        result_members.append({
            "member_name": m.name,
            "amount_cents": amount,
            "item_total_cents": amount,  # same for equal
            "delivery_share_cents": (delivery_cents + tax_cents) // n,
        })
    return {
        "total_cents": total_cents,
        "delivery_cents": delivery_cents,
        "tax_cents": tax_cents,
        "split_mode": "equal",
        "members": result_members,
    }
