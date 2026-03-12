"""
Menu Extractor — Extract structured menu data from images using Gemini Vision.

Supports: JPEG, PNG, WebP images of restaurant menus.
Returns: {categories: [{name, items: [{name, description, price_cents}]}]}
"""

import base64
import json as _json
import os
import urllib.parse
import urllib.request
from dotenv import load_dotenv


EXTRACTION_PROMPT = """You are extracting a restaurant menu from an uploaded image (photo of a printed menu, screenshot, etc).
Return JSON:
{
  "restaurant_name": "...",
  "categories": [
    {
      "name": "Category Name",
      "items": [{"name": "Dish Name", "description": "brief desc", "price_cents": 1299}]
    }
  ]
}
RULES:
- price_cents = cents ($12.99 → 1299). Use 0 if price is not visible.
- Every category MUST have at least one item. No empty categories.
- Extract EVERY food item visible in the image.
- Include appetizers, mains, sides, drinks, desserts — everything visible.
- If no clear categories exist, group into logical categories (e.g. "Main Dishes", "Drinks", "Sides").
- For handwritten menus, do your best to read each item.
- Always return valid JSON."""


MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _parse_json(raw_text: str) -> dict:
    """Parse JSON from AI response, handling ```json wrapping."""
    t = raw_text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.startswith("json"):
            t = t[4:]
    return _json.loads(t)


def extract_menu_from_image(image_bytes: bytes, filename: str = "menu.jpg") -> dict:
    """
    Extract menu from an image using Gemini Vision API.

    Args:
        image_bytes: Raw image file bytes.
        filename: Original filename (for MIME type detection).

    Returns:
        Structured menu dict: {restaurant_name, categories: [{name, items}]}
    """
    load_dotenv()

    # Determine MIME type
    ext = os.path.splitext(filename)[1].lower()
    mime_type = MIME_MAP.get(ext, "image/jpeg")

    # Base64 encode
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    menu_data = None

    # --- Try Gemini Vision first ---
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if gemini_key:
        try:
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}"

            body = _json.dumps({
                "contents": [{
                    "parts": [
                        {"text": f"Look at this restaurant menu image carefully. {EXTRACTION_PROMPT}"},
                        {"inline_data": {"mime_type": mime_type, "data": image_b64}},
                    ]
                }],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                }
            }).encode()

            req = urllib.request.Request(gemini_url, body, {"Content-Type": "application/json"})
            res = urllib.request.urlopen(req, timeout=120)
            data = _json.loads(res.read())
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            menu_data = _parse_json(text)
            print(f"[MenuExtractor] Gemini Vision extracted {sum(len(c.get('items', [])) for c in menu_data.get('categories', []))} items")
        except Exception as e:
            print(f"[MenuExtractor] Gemini Vision error: {e}")
            menu_data = None

    # --- Fallback to OpenAI GPT-4o-mini (vision) ---
    if not menu_data:
        oai_key = os.getenv("OPENAI_API_KEY", "")
        if oai_key:
            try:
                oai_url = "https://api.openai.com/v1/chat/completions"
                oai_body = _json.dumps({
                    "model": "gpt-4o-mini",
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": EXTRACTION_PROMPT},
                        {"role": "user", "content": [
                            {"type": "text", "text": "Extract the menu from this image."},
                            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}},
                        ]},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 16000,
                }).encode()

                req = urllib.request.Request(oai_url, oai_body, {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {oai_key}",
                })
                res = urllib.request.urlopen(req, timeout=120)
                data = _json.loads(res.read())
                text = data["choices"][0]["message"]["content"].strip()
                menu_data = _parse_json(text)
                print(f"[MenuExtractor] OpenAI extracted {sum(len(c.get('items', [])) for c in menu_data.get('categories', []))} items")
            except Exception as e:
                print(f"[MenuExtractor] OpenAI error: {e}")
                menu_data = None

    if not menu_data:
        raise ValueError("Failed to extract menu from image. Please try a clearer photo.")

    # Validate structure
    if "categories" not in menu_data:
        menu_data = {"categories": [], "restaurant_name": menu_data.get("restaurant_name", "Unknown")}

    # Ensure price_cents are integers
    for cat in menu_data.get("categories", []):
        for item in cat.get("items", []):
            try:
                item["price_cents"] = int(item.get("price_cents", 0))
            except (TypeError, ValueError):
                item["price_cents"] = 0
            if "description" not in item:
                item["description"] = ""

    return menu_data
