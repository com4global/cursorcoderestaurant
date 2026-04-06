"""
LLM-based extraction of multi-restaurant orders from a single utterance.

Used when rule-based _parse_multi_restaurant_order fails (e.g. varied phrasing,
typos, or "one soup from Anjappar 1 drink from Aroma").
"""
from __future__ import annotations

import json
import os
import re

_MULTI_ORDER_SYSTEM = """You extract food orders that mention multiple restaurants in one message.

Output JSON only, no markdown. Schema:
{
  "orders": [
    {
      "restaurant_name": "exact or best-guess restaurant name as stated or implied",
      "items": [
        { "item_name": "menu item as stated", "quantity": 1 }
      ]
    }
  ]
}

Rules:
- Only include if the user is clearly ordering from more than one restaurant (e.g. "from X and from Y", "X: item, Y: item").
- restaurant_name: use the name the user said (e.g. "Aroma", "Desi District", "Anjappar"). Normalize obvious typos.
- item_name: use what the user said (e.g. "chicken biryani", "soup", "drink", "butter masala"). Do not invent items.
- quantity: integer; default 1 if not stated.
- If the message is a single-restaurant order or not an order, return {"orders": []}.
"""


def extract_multi_order(text: str) -> list[dict] | None:
    """
    Use OpenAI to extract multi-restaurant order from natural language.
    Returns list of {"restaurant_name": str, "items": [{"item_name": str, "quantity": int}]}
    or None if LLM unavailable or message is not a multi-order.
    """
    cleaned = (text or "").strip()
    if not cleaned or len(cleaned) < 10:
        return None

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not openai_key:
        return None

    try:
        import openai
        client = openai.OpenAI(api_key=openai_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _MULTI_ORDER_SYSTEM},
                {"role": "user", "content": cleaned},
            ],
            temperature=0,
            max_tokens=400,
        )
        content = (response.choices[0].message.content or "").strip()
        if not content:
            return None
        # Strip markdown code block if present
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```\s*$", "", content).strip()
        data = json.loads(content)
        orders = data.get("orders") if isinstance(data, dict) else None
        if not orders or not isinstance(orders, list):
            return None
        out = []
        for o in orders:
            if not isinstance(o, dict):
                continue
            name = o.get("restaurant_name")
            items_raw = o.get("items")
            if not name or not isinstance(name, str) or not name.strip():
                continue
            if not isinstance(items_raw, list):
                continue
            items = []
            for it in items_raw:
                if not isinstance(it, dict):
                    continue
                iname = it.get("item_name")
                qty = it.get("quantity", 1)
                if not iname or not isinstance(iname, str) or not iname.strip():
                    continue
                try:
                    qty = int(qty) if qty is not None else 1
                except (TypeError, ValueError):
                    qty = 1
                if qty < 1:
                    qty = 1
                items.append({"item_name": iname.strip(), "quantity": qty})
            if items:
                out.append({"restaurant_name": name.strip(), "items": items})
        return out if out else None
    except Exception:
        return None
