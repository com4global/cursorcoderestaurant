from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="customer", nullable=False)  # customer, owner, admin
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    sessions = relationship("ChatSession", back_populates="user")
    orders = relationship("Order", back_populates="user")
    restaurants = relationship("Restaurant", back_populates="owner")
    taste_profile = relationship("TasteProfile", back_populates="user", uselist=False)


class Restaurant(Base):
    __tablename__ = "restaurants"

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    name = Column(String(200), nullable=False)
    slug = Column(String(200), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    city = Column(String(120), nullable=True)
    address = Column(String(300), nullable=True)
    zipcode = Column(String(10), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    phone = Column(String(20), nullable=True)
    notification_email = Column(String(255), nullable=True)
    notification_phone = Column(String(20), nullable=True)
    rating = Column(Float, nullable=True)  # 1.0-5.0 star rating
    avg_prep_minutes = Column(Integer, default=20, nullable=False)  # average prep time for ETA
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    owner = relationship("User", back_populates="restaurants")
    categories = relationship("MenuCategory", back_populates="restaurant", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="restaurant")


class MenuCategory(Base):
    __tablename__ = "menu_categories"

    id = Column(Integer, primary_key=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False)
    name = Column(String(120), nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    restaurant = relationship("Restaurant", back_populates="categories")
    items = relationship("MenuItem", back_populates="category")


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("menu_categories.id"), nullable=False)
    name = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    price_cents = Column(Integer, nullable=False)
    is_available = Column(Boolean, default=True, nullable=False)
    portion_people = Column(Integer, nullable=True)       # how many people this feeds
    cuisine = Column(String(60), nullable=True)            # e.g. "Indian", "Italian"
    protein_type = Column(String(40), nullable=True)       # e.g. "chicken", "veg", "paneer"
    tags = Column(Text, nullable=True)                     # JSON array: ["spicy", "vegetarian", "biryani"]
    calories = Column(Integer, nullable=True)
    prep_time_mins = Column(Integer, nullable=True)

    category = relationship("MenuCategory", back_populates="items")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False)
    status = Column(String(40), default="pending", nullable=False)
    total_cents = Column(Integer, default=0, nullable=False)
    estimated_ready_at = Column(DateTime, nullable=True)     # ETA for customer
    status_updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)  # last status change
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="orders")
    restaurant = relationship("Restaurant", back_populates="orders")
    items = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id"), nullable=True)  # nullable so menu can be replaced; order keeps quantity/price
    quantity = Column(Integer, nullable=False)
    price_cents = Column(Integer, nullable=False)

    order = relationship("Order", back_populates="items")


class OrderFeedback(Base):
    """Post-order feedback: rating, issues, comment, photo. Rating <= 2 escalates to restaurant."""
    __tablename__ = "order_feedbacks"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, unique=True)  # one feedback per order
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5
    issues = Column(Text, nullable=True)  # JSON array: ["cold_food", "taste_bad", ...]
    comment = Column(Text, nullable=True)
    photo_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    order = relationship("Order", backref="feedback")
    user = relationship("User", backref="order_feedbacks")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=True)
    category_id = Column(Integer, ForeignKey("menu_categories.id"), nullable=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    status = Column(String(40), default="active", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="sessions")
    messages = relationship("ChatMessage", back_populates="session")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String(40), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("ChatSession", back_populates="messages")


class TasteProfile(Base):
    """User taste preferences for AI flavor profile and personalized recommendations."""
    __tablename__ = "taste_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    spice_level = Column(String(20), default="medium", nullable=False)  # mild, medium, spicy
    diet = Column(String(40), nullable=True)  # any, vegetarian, vegan, halal
    liked_cuisines = Column(Text, nullable=True)  # JSON array of strings
    disliked_tags = Column(Text, nullable=True)  # free text e.g. "nuts, dairy"
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="taste_profile")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    plan = Column(String(20), default="free_trial", nullable=False)  # free_trial, standard, corporate
    status = Column(String(20), default="trialing", nullable=False)  # trialing, active, canceled, past_due
    stripe_customer_id = Column(String(255), nullable=True)
    stripe_subscription_id = Column(String(255), nullable=True)
    trial_start = Column(DateTime, nullable=True)
    trial_end = Column(DateTime, nullable=True)
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", backref="subscription_rel")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    subscription_id = Column(Integer, nullable=True)  # No FK — avoids UUID/int mismatch on Supabase
    stripe_payment_intent_id = Column(String(255), nullable=True)
    stripe_checkout_session_id = Column(String(255), nullable=True)
    amount_cents = Column(Integer, default=0, nullable=False)
    status = Column(String(40), default="pending", nullable=False)  # pending, completed, failed
    payment_type = Column(String(20), default="order", nullable=False)  # order, subscription
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", backref="payments")


# --- Group Ordering ---

class GroupOrderSession(Base):
    """A group order session: one share link, many members with preferences."""
    __tablename__ = "group_order_sessions"

    id = Column(Integer, primary_key=True)
    share_code = Column(String(20), unique=True, index=True, nullable=False)  # e.g. "8734" for app.com/group/8734
    creator_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # optional: logged-in creator
    status = Column(String(40), default="active", nullable=False)  # active, closed, ordered
    delivery_address_zipcode = Column(String(10), nullable=True)  # optional for distance scoring
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    creator = relationship("User", backref="group_sessions_created")
    members = relationship("GroupOrderMember", back_populates="group_session", cascade="all, delete-orphan")


class GroupOrderMember(Base):
    """A member in a group order: name, preference, budget, dietary restrictions."""
    __tablename__ = "group_order_members"

    id = Column(Integer, primary_key=True)
    group_session_id = Column(Integer, ForeignKey("group_order_sessions.id"), nullable=False)
    name = Column(String(120), nullable=False)
    preference = Column(String(200), nullable=True)  # e.g. "biryani", "veg", "spicy"
    budget_cents = Column(Integer, nullable=True)  # max spend per person
    dietary_restrictions = Column(String(200), nullable=True)  # e.g. "vegetarian", "no dairy"
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # optional: link to app user
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    group_session = relationship("GroupOrderSession", back_populates="members")
    user = relationship("User", backref="group_memberships")

