from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


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


class ItemUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price_cents: int | None = None
    is_available: bool | None = None


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

    model_config = {"from_attributes": True}


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


class ChatMessageOut(BaseModel):
    session_id: int
    reply: str
    restaurant_id: int | None = None
    category_id: int | None = None
    order_id: int | None = None
    categories: list[dict] | None = None
    items: list[dict] | None = None
    cart_summary: dict | None = None


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
