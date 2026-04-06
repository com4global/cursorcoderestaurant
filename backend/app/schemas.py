from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, model_validator


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str = "customer"


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class UserOut(BaseModel):
    id: int
    email: EmailStr
    role: str = "customer"
    created_at: datetime

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RestaurantOut(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None
    city: str | None
    address: str | None = None
    zipcode: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    distance_miles: float | None = None
    owner_id: int | None = None
    notification_email: str | None = None
    notification_phone: str | None = None

    model_config = {"from_attributes": True}


# --- Onboarding schemas ---
class RestaurantCreate(BaseModel):
    name: str = Field(min_length=2)
    description: str | None = None
    city: str | None = None
    address: str | None = None
    zipcode: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    phone: str | None = None
    notification_email: str | None = None
    notification_phone: str | None = None


class RestaurantUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    city: str | None = None
    address: str | None = None
    zipcode: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    phone: str | None = None
    is_active: bool | None = None
    notification_email: str | None = None
    notification_phone: str | None = None


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1)
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: str | None = None
    sort_order: int | None = None


class ItemCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    price_cents: int = Field(ge=0)
    is_available: bool = True
    portion_people: int | None = None
    cuisine: str | None = None
    protein_type: str | None = None
    tags: list[str] | None = None
    calories: int | None = None
    prep_time_mins: int | None = None


class ItemUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price_cents: int | None = None
    is_available: bool | None = None
    portion_people: int | None = None
    cuisine: str | None = None
    protein_type: str | None = None
    tags: list[str] | None = None
    calories: int | None = None
    prep_time_mins: int | None = None


class MenuCategoryOut(BaseModel):
    id: int
    name: str
    sort_order: int

    model_config = {"from_attributes": True}


class MenuItemOut(BaseModel):
    id: int
    name: str
    description: str | None
    price_cents: int
    is_available: bool
    portion_people: int | None = None
    cuisine: str | None = None
    protein_type: str | None = None
    tags: list[str] = []
    calories: int | None = None
    prep_time_mins: int | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def parse_tags_or_derive(cls, data):
        from app.taste_tags import derive_item_tags
        if hasattr(data, "name"):
            raw = getattr(data, "tags", None)
            name = getattr(data, "name", None)
            cuisine = getattr(data, "cuisine", None)
            protein_type = getattr(data, "protein_type", None)
            if raw is None or raw == "":
                tags = derive_item_tags(name, cuisine, protein_type)
            elif isinstance(raw, str):
                try:
                    tags = json.loads(raw) if raw.strip() else []
                except (json.JSONDecodeError, TypeError):
                    tags = []
            else:
                tags = list(raw) if raw else []
            if not isinstance(data, dict):
                data = {f: getattr(data, f, None) for f in ("id", "name", "description", "price_cents", "is_available", "portion_people", "cuisine", "protein_type", "calories", "prep_time_mins")}
            data["tags"] = tags
            return data
        if isinstance(data, dict):
            raw = data.get("tags")
            if raw is None or raw == "":
                data["tags"] = derive_item_tags(data.get("name"), data.get("cuisine"), data.get("protein_type"))
            elif isinstance(raw, str):
                try:
                    data["tags"] = json.loads(raw) if raw.strip() else []
                except (json.JSONDecodeError, TypeError):
                    data["tags"] = []
        return data


class ChatSessionOut(BaseModel):
    id: int
    status: str
    restaurant_id: int | None
    category_id: int | None
    order_id: int | None

    model_config = {"from_attributes": True}


class ChatMessageIn(BaseModel):
    session_id: int | None = None
    text: str
    restaurant_id: int | None = None
    lat: float | None = None
    lng: float | None = None


class ChatMessageOut(BaseModel):
    session_id: int
    reply: str
    restaurant_id: int | None = None
    category_id: int | None = None
    order_id: int | None = None
    categories: list[dict] | None = None
    items: list[dict] | None = None
    cart_summary: dict | None = None
    voice_prompt: str | None = None
    open_group_tab: bool | None = None  # True when user asked for group order → frontend opens Group tab


# --- Cart schemas ---

class CartItemOut(BaseModel):
    name: str
    quantity: int
    price_cents: int
    line_total_cents: int

class CartRestaurantGroup(BaseModel):
    restaurant_id: int
    restaurant_name: str
    order_id: int
    items: list[CartItemOut]
    subtotal_cents: int

class CartOut(BaseModel):
    restaurants: list[CartRestaurantGroup]
    grand_total_cents: int


# --- Order schemas ---

class OrderItemOut(BaseModel):
    name: str
    quantity: int
    price_cents: int

class OrderOut(BaseModel):
    id: int
    status: str
    total_cents: int
    created_at: str
    customer_email: str | None = None
    items: list[OrderItemOut]
    restaurant_name: str | None = None
    restaurant_id: int | None = None


# --- Payment schemas ---

class SubscriptionOut(BaseModel):
    id: int
    plan: str
    status: str
    trial_end: str | None = None
    current_period_end: str | None = None

    model_config = {"from_attributes": True}


class CheckoutSessionOut(BaseModel):
    checkout_url: str
    session_id: str


# --- Meal Optimizer schemas ---

class MealOptimizerRequest(BaseModel):
    people: int = Field(ge=1, le=50)
    budget_cents: int = Field(ge=100)  # $1 minimum
    cuisine: str | None = None
    restaurant_id: int | None = None


class MealOptimizerItem(BaseModel):
    item_id: int
    name: str
    quantity: int
    price_cents: int
    portion_people: int


class MealCombo(BaseModel):
    restaurant_name: str
    restaurant_id: int
    items: list[MealOptimizerItem]
    total_cents: int
    feeds_people: int
    score: float


class MealOptimizerResponse(BaseModel):
    combos: list[MealCombo]
    people_requested: int
    budget_cents: int


# --- Price Comparison schemas ---

class PriceComparisonItem(BaseModel):
    item_id: int
    item_name: str
    price_cents: int
    restaurant_name: str
    restaurant_id: int
    city: str | None = None
    rating: float | None = None
    description: str | None = None

class PriceComparisonResponse(BaseModel):
    query: str
    results: list[PriceComparisonItem]
    best_value: PriceComparisonItem | None = None


# --- Meal Plan schemas ---

class MealPlanDay(BaseModel):
    day: str
    item_id: int
    item_name: str
    restaurant_name: str
    restaurant_id: int
    price_cents: int
    cuisine: str | None = None
    description: str | None = None

class MealPlanResponse(BaseModel):
    days: list[MealPlanDay]
    total_cents: int
    budget_cents: int
    savings_cents: int
    people_count: int = 1
    ai_summary: str | None = None


# --- Taste Profile (AI Flavor / Recommendations) ---

class TasteProfileUpdate(BaseModel):
    spice_level: str | None = None
    diet: str | None = None
    liked_cuisines: list[str] | None = None
    disliked_tags: str | None = None


class TasteProfileOut(BaseModel):
    id: int
    user_id: int
    spice_level: str
    diet: str | None
    liked_cuisines: list[str]
    disliked_tags: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TasteHistorySummaryOut(BaseModel):
    ordered_item_ids: list[int]
    cuisine_counts: dict[str, int]
    protein_counts: dict[str, int]
    item_names: list[str]
    total_orders: int


class TasteRecommendationOut(BaseModel):
    menu_item_id: int
    name: str
    restaurant_id: int
    restaurant_name: str
    price_cents: int
    reason: str


# --- Post-Order Feedback ---

FEEDBACK_ISSUES = [
    "cold_food", "taste_bad", "missing_items", "late_delivery",
    "wrong_order", "packaging_issue", "other",
]


class FeedbackCreate(BaseModel):
    order_id: int
    rating: int = Field(ge=1, le=5)
    issues: list[str] | None = None  # from FEEDBACK_ISSUES when rating <= 3
    comment: str | None = None
    # photo: optional file upload handled separately


class FeedbackOut(BaseModel):
    id: int
    order_id: int
    rating: int
    issues: list[str]
    comment: str | None
    photo_url: str | None
    created_at: datetime
    escalated: bool  # True when rating <= 2

    model_config = {"from_attributes": True}


class ComplaintOut(BaseModel):
    """For restaurant dashboard: feedback that was escalated (rating <= 2)."""
    id: int
    order_id: int
    user_id: int
    rating: int
    issues: list[str]
    comment: str | None
    photo_url: str | None
    created_at: datetime
    restaurant_id: int
    restaurant_name: str
    order_items_summary: str


# --- Group Ordering ---

class GroupOrderSessionCreate(BaseModel):
    """Create a new group order session (optional: zipcode for distance)."""
    delivery_zipcode: str | None = None


class GroupOrderMemberIn(BaseModel):
    """Payload when joining a group: name, preference, budget, dietary restrictions."""
    name: str = Field(min_length=1, max_length=120)
    preference: str | None = Field(None, max_length=200)
    budget_cents: int | None = Field(None, ge=0)
    dietary_restrictions: str | None = Field(None, max_length=200)


class GroupOrderMemberOut(BaseModel):
    id: int
    name: str
    preference: str | None
    budget_cents: int | None
    dietary_restrictions: str | None

    model_config = {"from_attributes": True}


class GroupOrderSessionOut(BaseModel):
    id: int
    share_code: str
    status: str
    delivery_address_zipcode: str | None
    created_at: datetime
    members: list[GroupOrderMemberOut] = []

    model_config = {"from_attributes": True}


class GroupOrderRecommendationItem(BaseModel):
    """A suggested dish for the group."""
    item_id: int
    name: str
    price_cents: int
    quantity: int = 1
    portion_people: int | None = None


class GroupOrderRecommendationOut(BaseModel):
    """AI consensus: best restaurant + suggested dishes for the group."""
    restaurant_id: int
    restaurant_name: str
    suggested_items: list[GroupOrderRecommendationItem]
    total_cents: int
    estimated_per_person_cents: int
    reasons: list[str]  # e.g. "Within everyone's budget", "Veg option available"
    group_discount_message: str | None = None  # e.g. "Add $2 more for free delivery"


class GroupOrderSplitMember(BaseModel):
    """Per-member split: name and amount in cents."""
    member_name: str
    amount_cents: int
    item_total_cents: int  # for item-based; same as amount_cents for equal
    delivery_share_cents: int


class GroupOrderSplitOut(BaseModel):
    """Bill split result: total and per-member amounts."""
    total_cents: int
    delivery_cents: int = 0
    tax_cents: int = 0
    split_mode: str  # "equal" | "item"
    members: list[GroupOrderSplitMember]
