from __future__ import annotations

import json
from itertools import product
import os
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import crud, models, sarvam_service
from .auth import get_current_user
from .config import settings
from .db import get_db

router = APIRouter(prefix="/api/call-order", tags=["call-order"])

_ORDER_WORDS = {
    "order", "want", "need", "eat", "food", "dish", "menu", "hungry", "add", "buy", "get",
}
_GREETING_WORDS = {"hi", "hello", "hey", "vanakkam"}
_ASK_RESTAURANT_WORDS = {"restaurant", "hotel", "place", "shop"}
_GENERIC_RESTAURANT_TOKENS = {"restaurant", "hotel", "place", "shop", "cafe", "kitchen", "house"}
_CONFIRM_WORDS = {"yes", "yeah", "yep", "correct", "confirm", "ok", "okay", "sure"}
_NEGATIVE_WORDS = {"no", "nope", "cancel", "stop", "wrong"}
_REMOVE_WORDS = {"remove", "delete", "drop"}
_META_CORRECTION_WORDS = {"said", "meant", "actually", "wrong", "no"}
_GENERIC_DISH_WORDS = {
    "something", "anything", "food", "dish", "meal", "meals", "eat", "item", "items", "stuff",
    "okay", "ok", "alright", "allright", "fine", "thanks", "thank", "please",
}
_QUESTION_NOISE_WORDS = {
    "what", "which", "options", "option", "available", "availability", "have", "has", "had",
    "there", "list", "tell", "about", "show", "same", "type", "problem", "issue", "are",
    "is", "all", "any", "else", "kind", "kinds",
}
_RESTAURANT_QUERY_NOISE_WORDS = {
    "what", "which", "options", "option", "available", "availability", "there", "list", "tell",
    "about", "show", "type", "types", "are", "is", "all", "any", "kind", "kinds", "called",
    "named", "here", "near", "nearby", "around", "open", "called", "restaurant", "restaurants",
    "hotel", "place", "places", "cafe", "cafes", "shop", "shops", "called", "there", "called",
    "either", "available", "availability", "give", "find",
}
_ACKNOWLEDGEMENT_WORDS = {"ok", "okay", "alright", "allright", "fine", "thanks", "thank", "great", "cool"}
_FILLER_WORDS = {
    "i", "would", "like", "to", "have", "get", "me", "please", "can", "you", "show", "need",
    "want", "some", "a", "an", "the", "my", "for", "and", "with", "from", "order", "in", "of",
}
_CART_PHRASES = ("cart", "summary", "order summary", "what did i order", "what is in my order")
_CALL_ORDER_LLM_ACTIONS = {
    "select_restaurant",
    "ask_restaurant_clarification",
    "select_item",
    "ask_item_clarification",
    "confirm_add",
    "add_item",
    "summarize_cart",
    "ask_followup",
}
_NORMALIZATION_REPLACEMENTS = (
    (r"\bbiriyani\b|\bbriyani\b", "biryani"),
    (r"\bkulambu\b|\bkolambu\b|\bkolampu\b", "kuzhambu"),
    (r"\bsambhar\b|\bsaambar\b", "sambar"),
    (r"\braasam\b", "rasam"),
    (r"\bkoli\b|\bkozi\b|\bkazghi\b|\bkazgi\b", "kozhi"),
    (r"\bbarotta\b|\bporotta\b", "parotta"),
    (r"\bdosai\b|\bdhosa\b|\bdhosa\b", "dosa"),
    (r"\bidly\b|\biddli\b|\biddly\b", "idli"),
    (r"\buthapam\b|\buttapam\b|\buttappam\b|\bootappam\b", "uthappam"),
    (r"\bvadai\b|\bwada\b", "vada"),
    (r"\bthaali\b|\bthalee\b", "thali"),
    (r"\bpuri\b", "poori"),
    (r"\bpanir\b|\bpanneer\b", "paneer"),
    (r"\bmeals\b", "meal"),
    (r"\bsixty\s*five\b|\bsix\s*five\b", "65"),
    (r"\bchettinaad\b|\bchettinadu\b|\bchettinaadu\b|\bchettnad\b", "chettinad"),
    (r"\bnaatu\b", "nattu"),
)
_ALIAS_FAMILIES = {
    "biryani": ("biryani", "biriyani", "briyani", "biriani"),
    "kuzhambu": ("kuzhambu", "kulambu", "kolambu", "kolampu", "kozhambu"),
    "sambar": ("sambar", "sambhar", "saambar"),
    "rasam": ("rasam", "raasam"),
    "kozhi": ("kozhi", "kozi", "koli", "kozhii", "kazhi", "kazgi", "kazghi"),
    "parotta": ("parotta", "porotta", "barotta"),
    "nattu": ("nattu", "naatu"),
    "kurma": ("kurma", "korma", "kuruma"),
    "chapathi": ("chapathi", "chappathi", "chapati"),
    "idiyappam": ("idiyappam", "idiyapam", "idiappam", "idiappom"),
    "dosa": ("dosa", "dosai", "dhosa", "dhosa"),
    "idli": ("idli", "idly", "iddli", "iddly"),
    "uthappam": ("uthappam", "uthapam", "uttapam", "uttappam", "ootappam"),
    "vada": ("vada", "vadai", "wada"),
    "thali": ("thali", "thaali", "thalee"),
    "poori": ("poori", "puri"),
    "paneer": ("paneer", "panir", "panneer"),
    "meal": ("meal", "meals"),
    "65": ("65", "sixty five", "six five", "sixtyfive"),
    "chettinad": ("chettinad", "chettinaad", "chettinadu", "chettinaadu", "chettnad"),
    "sukka": ("sukka", "chukka"),
}
_ALIAS_TOKEN_TO_CANONICAL = {
    variant: canonical
    for canonical, variants in _ALIAS_FAMILIES.items()
    for variant in variants
}
_MAX_ALIAS_VARIANTS = 24


class CallOrderSessionCreate(BaseModel):
    language: str = Field(default="en-IN")


class CallOrderTurnIn(BaseModel):
    session_id: str
    transcript: str = Field(min_length=1)


class CallOrderSessionSummaryOut(BaseModel):
    ttl_minutes: int
    total_sessions: int
    active_sessions: int
    expired_sessions: int
    sessions_created_last_24h: int
    sessions_created_last_7d: int
    sessions_updated_last_24h: int
    oldest_active_updated_at: str | None = None
    newest_active_updated_at: str | None = None


def _normalize_language(language: str | None) -> str:
    return "ta-IN" if str(language or "").lower().startswith("ta") else "en-IN"


def _ensure_owner_or_admin(current_user) -> None:
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Not authorized")


def _assistant_greeting(language: str) -> str:
    if _normalize_language(language) == "ta-IN":
        return "வணக்கம். நான் உங்கள் உணவு ஆர்டர் உதவியாளர். எந்த உணவை தேடுகிறீர்கள்?"
    return "Hello. I am your AI food ordering assistant. Tell me what you would like to eat."


def _normalize_spoken_text(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    for pattern, replacement in _NORMALIZATION_REPLACEMENTS:
        normalized = re.sub(pattern, replacement, normalized)
    normalized = " ".join(_ALIAS_TOKEN_TO_CANONICAL.get(token, token) for token in normalized.split())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _alias_variants(text: str) -> list[str]:
    normalized = _normalize_spoken_text(text)
    tokens = normalized.split()
    if not tokens:
        return []

    variant_groups = [_ALIAS_FAMILIES.get(token, (token,)) for token in tokens]
    variants: list[str] = []
    for combo in product(*variant_groups):
        candidate = " ".join(combo)
        if candidate not in variants:
            variants.append(candidate)
        if len(variants) >= _MAX_ALIAS_VARIANTS:
            break
    if normalized not in variants:
        variants.insert(0, normalized)
    return variants[:_MAX_ALIAS_VARIANTS]


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _extract_focus_phrase(text: str) -> str:
    normalized = _normalize_spoken_text(text)
    tokens = [token for token in normalized.split() if token not in _FILLER_WORDS]
    return " ".join(tokens) if tokens else normalized


def _strip_restaurant_clause(text: str) -> str:
    normalized = _normalize_spoken_text(text)
    tokens = normalized.split()
    clause_indexes = [index for index, token in enumerate(tokens) if token in {"from", "at", "in"}]
    if not clause_indexes:
        return normalized
    stripped = " ".join(tokens[:clause_indexes[-1]]).strip()
    return stripped or normalized


def _extract_restaurant_phrase(text: str) -> str:
    normalized = _normalize_spoken_text(text)
    matches = re.finditer(r"\b(?:from|at|in)\s+([a-z0-9\s]+?)(?=\s+not\s+(?:from|at|in)\b|$)", normalized)
    for match in matches:
        phrase = _normalize_restaurant_name(match.group(1))
        if phrase:
            return phrase
    named_matches = re.finditer(r"\b(?:called|named)\s+([a-z0-9\s]+?)(?=$|\s+(?:here|near|nearby|around|please|today|there)\b)", normalized)
    for match in named_matches:
        phrase = _normalize_restaurant_name(match.group(1))
        if phrase:
            return phrase
    return ""


def _extract_negative_restaurant_phrases(text: str) -> list[str]:
    normalized = _normalize_spoken_text(text)
    phrases: list[str] = []
    matches = re.finditer(r"\bnot\s+(?:from|at|in)\s+([a-z0-9\s]+?)(?=$|\s+(?:but|instead|please)\b)", normalized)
    for match in matches:
        phrase = _normalize_restaurant_name(match.group(1))
        if phrase and phrase not in phrases:
            phrases.append(phrase)
    return phrases


def _normalize_restaurant_name(name: str) -> str:
    normalized = _normalize_spoken_text(name)
    tokens = [token for token in normalized.split() if token not in _GENERIC_RESTAURANT_TOKENS]
    return " ".join(tokens).strip() or normalized


def _restaurant_request_phrase(text: str) -> str:
    explicit_phrase = _extract_restaurant_phrase(text)
    if explicit_phrase:
        return explicit_phrase

    normalized = _normalize_spoken_text(text)
    tokens = [
        token for token in normalized.split()
        if token not in _FILLER_WORDS
        and token not in _QUESTION_NOISE_WORDS
        and token not in _RESTAURANT_QUERY_NOISE_WORDS
        and token not in _GENERIC_RESTAURANT_TOKENS
    ]
    return " ".join(tokens).strip()


def _dish_request_phrase(text: str) -> str:
    focus = _extract_focus_phrase(_strip_restaurant_clause(text))
    tokens = [
        token for token in focus.split()
        if len(token) > 1
        and token not in _FILLER_WORDS
        and token not in _GENERIC_DISH_WORDS
        and token not in _QUESTION_NOISE_WORDS
        and token not in _META_CORRECTION_WORDS
        and token not in _ORDER_WORDS
        and token not in _ASK_RESTAURANT_WORDS
    ]
    return " ".join(tokens).strip()


def _is_acknowledgement(text: str) -> bool:
    normalized = _normalize_spoken_text(text)
    tokens = [token for token in normalized.split() if token not in _FILLER_WORDS]
    if not tokens:
        return False
    return len(tokens) <= 3 and all(token in _ACKNOWLEDGEMENT_WORDS for token in tokens)


def _extract_quantity_from_message(text: str) -> int:
    word_to_num = {
        "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    lower = text.lower().strip()
    match = re.match(r"^(\d+)\s*(?:x\s*)?", lower)
    if match:
        return min(int(match.group(1)), 20)
    for word in lower.split():
        if word in word_to_num:
            return min(word_to_num[word], 20)
    return 1


def _has_add_intent(text: str) -> bool:
    lower = _normalize_spoken_text(text)
    return any(token in lower.split() for token in _ORDER_WORDS) or any(
        phrase in lower for phrase in ("i want", "i would like", "add", "give me", "get me", "can i have")
    )


def _has_remove_intent(text: str) -> bool:
    lower = _normalize_spoken_text(text)
    return any(token in lower.split() for token in _REMOVE_WORDS)


def _is_confirmation(text: str) -> bool:
    normalized = _normalize_spoken_text(text)
    tokens = set(normalized.split())
    if tokens & _CONFIRM_WORDS:
        return True
    return any(
        phrase in normalized
        for phrase in (
            "go ahead",
            "order that",
            "add that",
            "do that",
            "that one",
            "this one",
            "continue with that",
            "place that",
        )
    )


def _is_negative(text: str) -> bool:
    return bool(set(_normalize_spoken_text(text).split()) & _NEGATIVE_WORDS)


def _is_cart_request(text: str) -> bool:
    lower = _normalize_spoken_text(text)
    return any(phrase in lower for phrase in _CART_PHRASES)


def _should_use_llm() -> bool:
    if os.getenv("LLM_ENABLED", "true").strip().lower() == "false":
        return False
    return bool(os.getenv("SARVAM_API_KEY", "").strip())


def _should_use_call_order_llm_orchestrator() -> bool:
    return bool(settings.call_order_llm_orchestrator) and bool(os.getenv("SARVAM_API_KEY", "").strip())


def _cart_total_items(session: dict) -> int:
    return sum(int(item.get("quantity", 0)) for item in session.get("draft_cart", []))


def _cart_total_cents(session: dict) -> int:
    return sum(int(item.get("price_cents", 0)) * int(item.get("quantity", 0)) for item in session.get("draft_cart", []))


def _format_money(cents: int) -> str:
    return f"${(cents / 100):.2f}"


def _json_dump(value: object) -> str:
    return json.dumps(value)


def _json_load(payload: str | None, default: object) -> object:
    if not payload:
        return default
    try:
        return json.loads(payload)
    except (TypeError, ValueError):
        return default


def _session_snapshot(session: dict) -> dict:
    return {
        "session_id": session["id"],
        "language": session["language"],
        "state": session["state"],
        "assistant_reply": session.get("last_assistant_reply", ""),
        "history": list(session["history"]),
        "selected_restaurant": session.get("selected_restaurant"),
        "selected_item": session.get("selected_item"),
        "draft_cart": list(session.get("draft_cart", [])),
        "pending_action": session.get("pending_action"),
        "draft_total_items": _cart_total_items(session),
        "draft_total_cents": _cart_total_cents(session),
    }


def _history_context(history: list[dict]) -> str:
    recent = history[-6:]
    return "\n".join(f"{entry['role']}: {entry['text']}" for entry in recent)


def _session_from_record(record: models.CallOrderSession) -> dict:
    created_at = record.created_at.isoformat() if record.created_at else datetime.utcnow().isoformat()
    return {
        "id": record.session_id,
        "language": record.language,
        "state": record.state,
        "created_at": created_at,
        "history": list(_json_load(record.history_json, [])),
        "last_assistant_reply": record.last_assistant_reply or "",
        "selected_restaurant": _json_load(record.selected_restaurant_json, None),
        "selected_item": _json_load(record.selected_item_json, None),
        "draft_cart": list(_json_load(record.draft_cart_json, [])),
        "pending_action": _json_load(record.pending_action_json, None),
    }


def _session_expiry_cutoff() -> datetime:
    ttl_minutes = max(int(settings.call_order_session_ttl_minutes or 0), 1)
    return datetime.utcnow() - timedelta(minutes=ttl_minutes)


def _cleanup_expired_sessions(db: Session) -> None:
    cutoff = _session_expiry_cutoff()
    db.query(models.CallOrderSession).filter(models.CallOrderSession.updated_at < cutoff).delete()
    db.commit()


def _session_retention_summary(db: Session) -> CallOrderSessionSummaryOut:
    cutoff = _session_expiry_cutoff()
    now = datetime.utcnow()
    created_24h_cutoff = now - timedelta(hours=24)
    created_7d_cutoff = now - timedelta(days=7)
    updated_24h_cutoff = now - timedelta(hours=24)
    all_sessions = db.query(models.CallOrderSession).all()
    active_records = [record for record in all_sessions if record.updated_at and record.updated_at >= cutoff]
    expired_count = len(all_sessions) - len(active_records)
    created_last_24h = sum(1 for record in all_sessions if record.created_at and record.created_at >= created_24h_cutoff)
    created_last_7d = sum(1 for record in all_sessions if record.created_at and record.created_at >= created_7d_cutoff)
    updated_last_24h = sum(1 for record in all_sessions if record.updated_at and record.updated_at >= updated_24h_cutoff)
    ordered_active = sorted(active_records, key=lambda record: record.updated_at or datetime.utcnow())
    oldest_active = ordered_active[0].updated_at.isoformat() if ordered_active else None
    newest_active = ordered_active[-1].updated_at.isoformat() if ordered_active else None
    return CallOrderSessionSummaryOut(
        ttl_minutes=max(int(settings.call_order_session_ttl_minutes or 0), 1),
        total_sessions=len(all_sessions),
        active_sessions=len(active_records),
        expired_sessions=expired_count,
        sessions_created_last_24h=created_last_24h,
        sessions_created_last_7d=created_last_7d,
        sessions_updated_last_24h=updated_last_24h,
        oldest_active_updated_at=oldest_active,
        newest_active_updated_at=newest_active,
    )


def _get_session_record(db: Session, session_id: str) -> models.CallOrderSession | None:
    cutoff = _session_expiry_cutoff()
    record = db.query(models.CallOrderSession).filter(models.CallOrderSession.session_id == session_id).first()
    if not record:
        return None
    if record.updated_at and record.updated_at < cutoff:
        db.delete(record)
        db.commit()
        return None
    return record


def _persist_session(db: Session, session: dict, record: models.CallOrderSession | None = None) -> dict:
    _cleanup_expired_sessions(db)
    existing = record or _get_session_record(db, session["id"])
    if existing is None:
        existing = models.CallOrderSession(session_id=session["id"])
        db.add(existing)

    existing.language = session["language"]
    existing.state = session["state"]
    existing.history_json = _json_dump(session.get("history", []))
    existing.selected_restaurant_json = _json_dump(session.get("selected_restaurant")) if session.get("selected_restaurant") is not None else None
    existing.selected_item_json = _json_dump(session.get("selected_item")) if session.get("selected_item") is not None else None
    existing.draft_cart_json = _json_dump(session.get("draft_cart", []))
    existing.pending_action_json = _json_dump(session.get("pending_action")) if session.get("pending_action") is not None else None
    existing.last_assistant_reply = session.get("last_assistant_reply") or ""
    existing.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(existing)
    return _session_from_record(existing)


def _restaurant_candidates(db: Session, transcript: str) -> list[dict]:
    query = _restaurant_request_phrase(transcript) or _extract_focus_phrase(transcript)
    negative_phrases = _extract_negative_restaurant_phrases(transcript)
    query_variants = _alias_variants(query) or ([query] if query else [])
    restaurants = crud.list_restaurants(db)
    scored: list[tuple[float, object]] = []
    for restaurant in restaurants:
        name = _normalize_restaurant_name(restaurant.name)
        name_variants = _alias_variants(name) or [name]
        if any(
            negative == name
            or negative in name
            or name in negative
            or _similarity(negative, name) >= 0.74
            for negative in negative_phrases
        ):
            continue
        token_bonus = 0.0
        for token in query.split():
            if len(token) >= 3 and any(token in variant.split() for variant in name_variants):
                token_bonus += 0.18
        alias_score = max(
            (
                max(
                    _similarity(query_variant, name_variant),
                    _similarity(query_variant.replace(" ", ""), name_variant.replace(" ", "")),
                )
                for query_variant in query_variants
                for name_variant in name_variants
            ),
            default=0.0,
        )
        score = max(alias_score, 1.0 if query and any(query_variant == name_variant for query_variant in query_variants for name_variant in name_variants) else 0.0, min(1.0, token_bonus))
        if query and any(query_variant in name_variant or name_variant in query_variant for query_variant in query_variants for name_variant in name_variants):
            score = max(score, 0.96)
        if score >= 0.55:
            scored.append((score, restaurant))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {"id": restaurant.id, "name": restaurant.name, "score": round(score, 3), "type": "restaurant"}
        for score, restaurant in scored[:3]
    ]


def _item_candidates(db: Session, transcript: str, restaurant_id: int | None = None) -> list[dict]:
    query = _dish_request_phrase(transcript)
    if not query:
        return []
    query_variants = _alias_variants(query)

    restaurants = crud.list_restaurants(db)
    candidates: list[dict] = []
    for restaurant in restaurants:
        if restaurant_id is not None and restaurant.id != restaurant_id:
            continue
        for category in crud.list_categories(db, restaurant.id):
            for item in crud.list_items(db, category.id):
                normalized_item = _normalize_spoken_text(item.name)
                item_aliases = _alias_variants(item.name)
                token_bonus = 0.0
                for token in query.split():
                    if len(token) >= 3 and any(token in alias for alias in item_aliases):
                        token_bonus += 0.12
                alias_score = max(
                    (_similarity(query_variant, item_alias) for query_variant in query_variants for item_alias in item_aliases),
                    default=0.0,
                )
                score = max(alias_score, min(1.0, token_bonus))
                if any(query_variant == item_alias for query_variant in query_variants for item_alias in item_aliases):
                    score = 1.0
                elif any(item_alias in query_variant and len(item_alias) >= 4 for query_variant in query_variants for item_alias in item_aliases):
                    score = max(score, 0.93)
                elif any(query_variant in item_alias and len(query_variant) >= 4 for query_variant in query_variants for item_alias in item_aliases):
                    score = max(score, 0.89)
                if score >= 0.58:
                    candidates.append({
                        "type": "item",
                        "id": item.id,
                        "name": item.name,
                        "price_cents": item.price_cents,
                        "restaurant_id": restaurant.id,
                        "restaurant_name": restaurant.name,
                        "category_id": category.id,
                        "category_name": category.name,
                        "score": round(score, 3),
                    })
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[:3]


def _summarize_cart(session: dict) -> str:
    cart = session.get("draft_cart", [])
    if not cart:
        return "Your draft order is empty. Tell me the restaurant and dish you want to add."
    items_text = ", ".join(f"{item['quantity']} {item['name']}" for item in cart[:4])
    if len(cart) > 4:
        items_text += f", and {len(cart) - 4} more items"
    total = _format_money(_cart_total_cents(session))
    return f"Your draft order has {items_text}. Current total is {total}."


def _candidate_by_id(candidates: list[dict], candidate_id: int | None) -> dict | None:
    if not candidate_id:
        return None
    return next((candidate for candidate in candidates if int(candidate.get("id") or 0) == int(candidate_id)), None)


def _dedupe_candidates(candidates: list[dict], limit: int = 5) -> list[dict]:
    unique: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for candidate in candidates:
        key = (str(candidate.get("type") or ""), int(candidate.get("id") or 0))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
        if len(unique) >= limit:
            break
    return unique


def _related_item_candidates(db: Session, item: dict, limit: int = 5) -> list[dict]:
    category_id = int(item.get("category_id") or 0)
    restaurant_id = int(item.get("restaurant_id") or 0)
    if category_id <= 0 or restaurant_id <= 0:
        return [item]

    related: list[dict] = []
    for candidate in crud.list_items(db, category_id):
        related.append({
            "type": "item",
            "id": candidate.id,
            "name": candidate.name,
            "price_cents": candidate.price_cents,
            "restaurant_id": restaurant_id,
            "restaurant_name": item.get("restaurant_name"),
            "category_id": category_id,
            "category_name": item.get("category_name"),
            "score": item.get("score", 1.0) if candidate.id == item.get("id") else 0.75,
        })
    return _dedupe_candidates([item] + related, limit=limit)


def _coerce_int(value: object, default: int | None = None) -> int | None:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_json_object(payload: str) -> dict:
    text = str(payload or "").strip()
    if not text:
        raise ValueError("Empty LLM response")
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("LLM response did not contain JSON")
    return json.loads(match.group(0))


def _call_order_llm_context(session: dict, transcript: str, restaurant_hits: list[dict], item_hits: list[dict]) -> str:
    payload = {
        "language": session.get("language"),
        "transcript": transcript,
        "selected_restaurant": session.get("selected_restaurant"),
        "selected_item": session.get("selected_item"),
        "pending_action": session.get("pending_action"),
        "draft_cart": session.get("draft_cart", []),
        "history": session.get("history", [])[-8:],
        "restaurant_candidates": restaurant_hits,
        "item_candidates": item_hits,
        "allowed_actions": sorted(_CALL_ORDER_LLM_ACTIONS),
    }
    return json.dumps(payload, ensure_ascii=True)


def _call_order_llm_decision(session: dict, transcript: str, restaurant_hits: list[dict], item_hits: list[dict]) -> dict:
    system_prompt = (
        "You are the decision engine for a voice-first food ordering call. "
        "Return JSON only. Do not include markdown. "
        "Choose exactly one action from the allowed_actions list. "
        "Drive the conversation naturally and ask one short question at a time. "
        "Prefer clarification over saying a dish is unavailable. "
        "If the user is choosing a restaurant, use select_restaurant or ask_restaurant_clarification. "
        "If the user is exploring menu choices, use ask_item_clarification or ask_followup. "
        "Only use confirm_add or add_item when there is a valid item candidate or pending item. "
        "If there is an existing pending_action and the user asks a follow-up question, keep the conversation focused instead of cancelling it. "
        "Output schema: {reply, action, restaurant_id, item_id, quantity, use_pending_item}."
    )
    raw = sarvam_service.chat_completion(transcript, system_prompt, _call_order_llm_context(session, transcript, restaurant_hits, item_hits)).strip()
    decision = _extract_json_object(raw)
    action = str(decision.get("action") or "").strip()
    if action not in _CALL_ORDER_LLM_ACTIONS:
        raise ValueError(f"Unsupported LLM action: {action}")
    return decision


def _apply_call_order_llm_decision(
    session: dict,
    decision: dict,
    restaurant_hits: list[dict],
    item_hits: list[dict],
    db: Session,
) -> tuple[str, list[dict], dict]:
    reply = str(decision.get("reply") or "").strip()
    action = str(decision.get("action") or "").strip()
    restaurant_id = _coerce_int(decision.get("restaurant_id"))
    item_id = _coerce_int(decision.get("item_id"))
    quantity = max(1, min(_coerce_int(decision.get("quantity"), 1) or 1, 20))
    use_pending_item = bool(decision.get("use_pending_item"))
    updates: dict = {}

    selected_restaurant = _candidate_by_id(restaurant_hits, restaurant_id)
    current_restaurant = session.get("selected_restaurant") or {}
    if selected_restaurant is None and restaurant_id and int(current_restaurant.get("id") or 0) == restaurant_id:
        selected_restaurant = current_restaurant

    selected_item = _candidate_by_id(item_hits, item_id)
    pending_action = session.get("pending_action") or {}
    pending_item = pending_action.get("item") if isinstance(pending_action, dict) else None
    if selected_item is None and pending_item and int(pending_item.get("id") or 0) == int(item_id or 0):
        selected_item = pending_item
    if selected_item is None and use_pending_item and pending_item:
        selected_item = pending_item

    if action == "select_restaurant":
        if not selected_restaurant:
            raise ValueError("LLM selected an unknown restaurant")
        updates["selected_restaurant"] = selected_restaurant
        updates["selected_item"] = None
        updates["pending_action"] = None
        return reply or f"I found {selected_restaurant['name']}. Tell me the dish you want from there.", restaurant_hits, updates

    if action == "ask_restaurant_clarification":
        return reply or "Which restaurant did you mean?", restaurant_hits, updates

    if action in {"select_item", "confirm_add"}:
        if not selected_item:
            raise ValueError("LLM selected an unknown item")
        updates["selected_item"] = selected_item
        updates["selected_restaurant"] = {
            "id": selected_item["restaurant_id"],
            "name": selected_item["restaurant_name"],
            "type": "restaurant",
            "score": selected_item.get("score", 1.0),
        }
        updates["pending_action"] = {
            "type": "add_item",
            "quantity": quantity,
            "item": selected_item,
        }
        return (
            reply or f"I heard {quantity} {selected_item['name']} from {selected_item['restaurant_name']}. Should I add it to your draft order?",
            item_hits or [selected_item],
            updates,
        )

    if action == "add_item":
        if not selected_item:
            raise ValueError("LLM tried to add an unknown item")
        _add_to_draft_cart(session, selected_item, quantity)
        updates["selected_item"] = selected_item
        updates["selected_restaurant"] = {
            "id": selected_item["restaurant_id"],
            "name": selected_item["restaurant_name"],
            "type": "restaurant",
            "score": selected_item.get("score", 1.0),
        }
        updates["pending_action"] = None
        return reply or f"Added {quantity} {selected_item['name']} to your draft order. {_summarize_cart(session)}", [], updates

    if action == "ask_item_clarification":
        if selected_restaurant:
            updates["selected_restaurant"] = selected_restaurant
        elif selected_item:
            updates["selected_restaurant"] = {
                "id": selected_item["restaurant_id"],
                "name": selected_item["restaurant_name"],
                "type": "restaurant",
                "score": selected_item.get("score", 1.0),
            }
        if selected_item:
            updates["selected_item"] = selected_item
        suggestions = item_hits
        if selected_item:
            suggestions = _related_item_candidates(db, selected_item)
        return reply or "Which item did you mean?", suggestions, updates

    if action == "summarize_cart":
        return reply or _summarize_cart(session), [], updates

    if action == "ask_followup":
        if selected_restaurant:
            updates["selected_restaurant"] = selected_restaurant
        if selected_item:
            updates["selected_item"] = selected_item
        suggestions = item_hits or restaurant_hits
        return reply or "Tell me a bit more so I can help with the next step.", suggestions, updates

    raise ValueError(f"Unhandled LLM action: {action}")


def _llm_orchestrated_reply(session: dict, transcript: str, db: Session) -> tuple[str, list[dict], dict]:
    pending_result = _handle_pending_action(session, transcript)
    if pending_result is not None:
        return pending_result

    remove_result = _handle_remove_action(session, transcript, db)
    if remove_result is not None:
        return remove_result

    if _is_cart_request(transcript):
        return _summarize_cart(session), [], {}

    current_restaurant = session.get("selected_restaurant") or {}
    restaurant_hits = _restaurant_candidates(db, transcript)
    scoped_item_hits = _item_candidates(db, transcript, current_restaurant.get("id") if current_restaurant else None)
    global_item_hits = _item_candidates(db, transcript, None)
    item_hits = _dedupe_candidates(scoped_item_hits + global_item_hits, limit=5)
    decision = _call_order_llm_decision(session, transcript, restaurant_hits, item_hits)
    return _apply_call_order_llm_decision(session, decision, restaurant_hits, item_hits, db)


def _add_to_draft_cart(session: dict, candidate: dict, quantity: int) -> None:
    cart = session.setdefault("draft_cart", [])
    existing = next((item for item in cart if item["id"] == candidate["id"]), None)
    if existing:
        existing["quantity"] += quantity
        return
    cart.append({
        "id": candidate["id"],
        "name": candidate["name"],
        "price_cents": candidate.get("price_cents", 0),
        "quantity": quantity,
        "restaurant_id": candidate.get("restaurant_id"),
        "restaurant_name": candidate.get("restaurant_name"),
        "category_id": candidate.get("category_id"),
        "category_name": candidate.get("category_name"),
    })


def _remove_from_draft_cart(session: dict, candidate: dict | None, quantity: int) -> bool:
    cart = session.get("draft_cart", [])
    if not cart:
        return False
    target = None
    if candidate is not None:
        target = next((item for item in cart if item["id"] == candidate["id"]), None)
    if target is None and session.get("selected_item"):
        selected = session["selected_item"]
        target = next((item for item in cart if item["id"] == selected["id"]), None)
    if target is None:
        return False
    target["quantity"] -= quantity
    if target["quantity"] <= 0:
        cart.remove(target)
    return True


def _handle_pending_action(session: dict, transcript: str) -> tuple[str, list[dict], dict] | None:
    pending = session.get("pending_action")
    if not pending:
        return None
    if _is_confirmation(transcript):
        if pending["type"] == "add_item":
            _add_to_draft_cart(session, pending["item"], pending["quantity"])
            session["pending_action"] = None
            return (
                f"Added {pending['quantity']} {pending['item']['name']} to your draft order. {_summarize_cart(session)}",
                [],
                {"selected_item": pending["item"], "pending_action": None},
            )
    if _is_negative(transcript):
        item = pending.get("item")
        session["pending_action"] = None
        if item:
            return (f"Okay, I will not add {item['name']}. Tell me what you want instead.", [], {"pending_action": None})
        return ("Okay, cancelled. Tell me what you want instead.", [], {"pending_action": None})
    return None


def _handle_remove_action(session: dict, transcript: str, db: Session) -> tuple[str, list[dict], dict] | None:
    if not _has_remove_intent(transcript):
        return None
    candidate = None
    item_hits = _item_candidates(db, transcript, (session.get("selected_restaurant") or {}).get("id"))
    if item_hits:
        candidate = item_hits[0]
    quantity = _extract_quantity_from_message(transcript)
    removed = _remove_from_draft_cart(session, candidate, quantity)
    if not removed:
        return (
            "I could not find that item in your draft order. Ask for the order summary if you want to review it.",
            item_hits,
            {},
        )
    item_name = candidate["name"] if candidate else "that item"
    return (f"Removed {quantity} {item_name} from your draft order. {_summarize_cart(session)}", item_hits, {})


def _heuristic_reply(session: dict, transcript: str, db: Session) -> tuple[str, list[dict], dict]:
    normalized = _normalize_spoken_text(transcript)
    suggestions: list[dict] = []
    updates: dict = {}
    dish_phrase = _dish_request_phrase(transcript)

    pending_result = _handle_pending_action(session, transcript)
    if pending_result is not None:
        return pending_result

    remove_result = _handle_remove_action(session, transcript, db)
    if remove_result is not None:
        return remove_result

    if _is_cart_request(transcript):
        return _summarize_cart(session), suggestions, updates

    if _is_acknowledgement(transcript):
        restaurant = session.get("selected_restaurant")
        if session.get("draft_cart"):
            if restaurant:
                return (
                    f"Okay. You can tell me another dish from {restaurant['name']}, or ask for your order summary.",
                    suggestions,
                    updates,
                )
            return (
                "Okay. Tell me another dish, or ask for your order summary.",
                suggestions,
                updates,
            )
        if restaurant:
            return (
                f"Okay. Tell me the dish you want from {restaurant['name']}.",
                suggestions,
                updates,
            )
        return "Okay. Tell me the restaurant or dish you want.", suggestions, updates

    if not normalized:
        return "I may have missed that. Please say the dish name once more.", suggestions, updates

    if any(word in normalized.split() for word in _GREETING_WORDS):
        restaurants = crud.list_restaurants(db)
        if restaurants:
            names = ", ".join(restaurant.name for restaurant in restaurants[:3])
            return f"I can help with restaurants like {names}. Which one would you like to order from?", suggestions, updates
        return "I can help you order food. Tell me the restaurant or dish you want.", suggestions, updates

    explicit_restaurant_phrase = _extract_restaurant_phrase(transcript)
    restaurant_hits = _restaurant_candidates(db, transcript)
    if explicit_restaurant_phrase and restaurant_hits:
        updates["selected_restaurant"] = restaurant_hits[0]

    if explicit_restaurant_phrase and restaurant_hits and not dish_phrase:
        top_restaurant = restaurant_hits[0]
        updates["selected_restaurant"] = top_restaurant
        updates["pending_action"] = None
        updates["selected_item"] = None
        return f"I found {top_restaurant['name']}. Tell me the dish you want from there.", restaurant_hits, updates

    selected_restaurant = updates.get("selected_restaurant") or session.get("selected_restaurant") or {}
    selected_restaurant_id = selected_restaurant.get("id")
    pending_action = session.get("pending_action") or {}
    pending_item = pending_action.get("item") or {}
    if explicit_restaurant_phrase and selected_restaurant_id and pending_item.get("restaurant_id") != selected_restaurant_id:
        updates["pending_action"] = None
        updates["selected_item"] = None

    global_item_hits: list[dict] = []
    if selected_restaurant_id:
        item_hits = _item_candidates(db, transcript, selected_restaurant_id)
        if item_hits and item_hits[0]["score"] < 0.84:
            item_hits = []
        if not item_hits:
            global_item_hits = _item_candidates(db, transcript, None)
            if (
                global_item_hits
                and not explicit_restaurant_phrase
                and _has_add_intent(transcript)
                and global_item_hits[0]["score"] >= 0.88
                and (global_item_hits[0]["score"] - (global_item_hits[1]["score"] if len(global_item_hits) > 1 else 0)) >= 0.08
            ):
                item_hits = global_item_hits
    else:
        item_hits = _item_candidates(db, transcript, None)

    if item_hits:
        top_item = item_hits[0]
        if top_item.get("restaurant_id") and (selected_restaurant.get("id") != top_item.get("restaurant_id")):
            updates["selected_restaurant"] = {
                "id": top_item["restaurant_id"],
                "name": top_item["restaurant_name"],
                "type": "restaurant",
                "score": top_item.get("score", 0),
            }
        score_gap = top_item["score"] - (item_hits[1]["score"] if len(item_hits) > 1 else 0)
        updates["selected_item"] = top_item
        if top_item["score"] >= 0.88 and score_gap >= 0.08:
            quantity = _extract_quantity_from_message(transcript)
            updates["pending_action"] = {
                "type": "add_item",
                "quantity": quantity,
                "item": top_item,
            }
            if _has_add_intent(transcript):
                return (
                    f"I heard {quantity} {top_item['name']} from {top_item['restaurant_name']}. Should I add it to your draft order?",
                    item_hits,
                    updates,
                )
            return (
                f"I heard {quantity} {top_item['name']} from {top_item['restaurant_name']}. Should I add it to your draft order?",
                item_hits,
                updates,
            )
        names = ", ".join(item["name"] for item in item_hits)
        return (f"I may have heard that as {names}. Which one did you mean?", item_hits, updates)

    should_treat_as_dish_miss = bool(
        selected_restaurant_id
        and dish_phrase
        and (
            not explicit_restaurant_phrase
            or _has_add_intent(transcript)
            or len(dish_phrase.split()) > 1
        )
        and not (len(dish_phrase.split()) == 1 and dish_phrase in _META_CORRECTION_WORDS)
    )
    if should_treat_as_dish_miss:
        if global_item_hits and global_item_hits[0].get("restaurant_id") != selected_restaurant_id:
            alternatives = ", ".join(
                f"{item['name']} from {item['restaurant_name']}"
                for item in global_item_hits[:2]
            )
            return (
                f"I found {selected_restaurant['name']}, but I could not match {dish_phrase} there. I did find {alternatives}. Do you want one of those, or another dish from {selected_restaurant['name']}?",
                global_item_hits,
                updates,
            )
        return (
            f"I found {selected_restaurant['name']}, but I could not match {dish_phrase} there. Tell me another dish from {selected_restaurant['name']}.",
            suggestions,
            updates,
        )

    if restaurant_hits and explicit_restaurant_phrase:
        top_restaurant = restaurant_hits[0]
        updates["selected_restaurant"] = top_restaurant
        return f"I found {top_restaurant['name']}. Tell me the dish you want from there.", restaurant_hits, updates

    if restaurant_hits and any(word in normalized for word in _ASK_RESTAURANT_WORDS):
        top_restaurant = restaurant_hits[0]
        updates["selected_restaurant"] = top_restaurant
        return f"I found {top_restaurant['name']}. Tell me the dish you want from there.", restaurant_hits, updates

    if any(word in normalized.split() for word in _ORDER_WORDS):
        restaurant = session.get("selected_restaurant")
        if restaurant:
            return (
                f"Tell me the dish name from {restaurant['name']}. If the pronunciation is tricky, say the closest spelling and I will confirm it with you.",
                suggestions,
                updates,
            )
        restaurants = crud.list_restaurants(db)
        if restaurants:
            names = ", ".join(restaurant.name for restaurant in restaurants[:3])
            return f"Tell me the restaurant first. Available options include {names}.", suggestions, updates

    return (
        "I do not want to guess and say something is unavailable. Please repeat the dish name, or tell me the restaurant first.",
        suggestions,
        updates,
    )


def _llm_reply(session: dict, transcript: str, db: Session) -> str:
    restaurant_context = session.get("selected_restaurant")
    item_hits = _item_candidates(db, transcript, restaurant_context.get("id") if restaurant_context else None)
    restaurant_hits = _restaurant_candidates(db, transcript)
    context_parts = []
    if restaurant_context:
        context_parts.append(f"Selected restaurant: {restaurant_context['name']}")
    if restaurant_hits:
        context_parts.append("Restaurant candidates: " + ", ".join(hit["name"] for hit in restaurant_hits))
    if item_hits:
        context_parts.append("Item candidates: " + ", ".join(hit["name"] for hit in item_hits))
    if session.get("draft_cart"):
        context_parts.append("Draft cart: " + ", ".join(f"{item['quantity']} {item['name']}" for item in session["draft_cart"]))
    history = _history_context(session["history"])
    if history:
        context_parts.append("Recent history:\n" + history)

    system_prompt = (
        "You are a human-like food ordering call assistant. "
        "Be short, natural, and helpful. "
        "If the dish name may have been misheard, never say it is unavailable immediately. "
        "Instead confirm likely dish names, ask one short clarifying question, and avoid robotic phrasing. "
        "If a restaurant candidate exists, guide the user toward it. "
        "If the user wants to add an item, confirm before adding it. "
        "Keep the reply under 40 words."
    )
    return sarvam_service.chat_completion(transcript, system_prompt, "\n\n".join(context_parts)).strip()


def _generate_reply(session: dict, transcript: str, db: Session) -> tuple[str, list[dict], dict]:
    if _should_use_call_order_llm_orchestrator():
        try:
            return _llm_orchestrated_reply(session, transcript, db)
        except Exception:
            pass
    heuristic_reply, suggestions, updates = _heuristic_reply(session, transcript, db)
    if not _should_use_llm():
        return heuristic_reply, suggestions, updates
    try:
        reply = _llm_reply(session, transcript, db)
        return reply or heuristic_reply, suggestions, updates
    except Exception:
        return heuristic_reply, suggestions, updates


def _finalize_draft_cart(session: dict, db: Session, user_id: int) -> tuple[int, int]:
    cart = session.get("draft_cart", [])
    if not cart:
        raise HTTPException(status_code=400, detail="Draft order is empty")

    touched_orders: dict[int, models.Order] = {}
    added_items = 0
    for draft_item in cart:
        menu_item_id = int(draft_item.get("id") or 0)
        restaurant_id = int(draft_item.get("restaurant_id") or 0)
        quantity = int(draft_item.get("quantity") or 0)
        if menu_item_id <= 0 or restaurant_id <= 0 or quantity <= 0:
            raise HTTPException(status_code=400, detail="Draft order contains invalid items")

        menu_item = db.query(models.MenuItem).filter(models.MenuItem.id == menu_item_id).first()
        if not menu_item or not menu_item.is_available:
            raise HTTPException(status_code=400, detail=f"{draft_item.get('name', 'An item')} is no longer available")

        order = touched_orders.get(restaurant_id)
        if order is None:
            order = crud.get_user_order_for_restaurant(db, user_id, restaurant_id)
            if not order:
                order = crud.create_order(db, user_id, restaurant_id)
            touched_orders[restaurant_id] = order

        crud.add_order_item(db, order, menu_item, quantity)
        added_items += quantity

    for order in touched_orders.values():
        crud.recompute_order_total(db, order)

    return added_items, len(touched_orders)


@router.post("/session")
def create_call_order_session(payload: CallOrderSessionCreate, db: Session = Depends(get_db)):
    language = _normalize_language(payload.language)
    session_id = uuid4().hex
    greeting = _assistant_greeting(language)
    session = {
        "id": session_id,
        "language": language,
        "state": "ready",
        "created_at": datetime.utcnow().isoformat(),
        "history": [{"role": "assistant", "text": greeting}],
        "last_assistant_reply": greeting,
        "selected_restaurant": None,
        "selected_item": None,
        "draft_cart": [],
        "pending_action": None,
    }
    persisted = _persist_session(db, session)
    return _session_snapshot(persisted)


@router.get("/session/{session_id}")
def get_call_order_session(session_id: str, db: Session = Depends(get_db)):
    record = _get_session_record(db, session_id)
    if not record:
        raise HTTPException(status_code=404, detail="Call session not found")
    return _session_snapshot(_session_from_record(record))


@router.post("/turn")
def process_call_order_turn(payload: CallOrderTurnIn, db: Session = Depends(get_db)):
    transcript = payload.transcript.strip()
    record = _get_session_record(db, payload.session_id)
    if not record:
        raise HTTPException(status_code=404, detail="Call session not found")
    if not transcript:
        raise HTTPException(status_code=400, detail="Transcript cannot be empty")

    session = _session_from_record(record)

    session["state"] = "processing"
    session["history"].append({"role": "user", "text": transcript})

    reply, suggestions, updates = _generate_reply(session, transcript, db)
    session.update(updates)
    session["history"].append({"role": "assistant", "text": reply})
    session["last_assistant_reply"] = reply
    session["state"] = "ready"

    persisted = _persist_session(db, session, record)
    result = _session_snapshot(persisted)
    result["suggestions"] = suggestions
    return result


@router.post("/session/{session_id}/finalize")
def finalize_call_order_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    record = _get_session_record(db, session_id)
    if not record:
        raise HTTPException(status_code=404, detail="Call session not found")

    session = _session_from_record(record)

    added_items, restaurant_count = _finalize_draft_cart(session, db, current_user.id)
    reply = (
        f"Moved {added_items} item{'s' if added_items != 1 else ''} from your draft order into your cart "
        f"across {restaurant_count} restaurant{'s' if restaurant_count != 1 else ''}."
    )
    session["draft_cart"] = []
    session["pending_action"] = None
    session["last_assistant_reply"] = reply
    session["history"].append({"role": "assistant", "text": reply})

    persisted = _persist_session(db, session, record)
    result = _session_snapshot(persisted)
    result["materialized_item_count"] = added_items
    result["materialized_restaurant_count"] = restaurant_count
    return result


@router.get("/admin/summary", response_model=CallOrderSessionSummaryOut)
def get_call_order_admin_summary(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _ensure_owner_or_admin(current_user)
    return _session_retention_summary(db)
