from sqlalchemy import func
from sqlalchemy.orm import Session

from .auth import hash_password
from .models import (
    ChatMessage,
    ChatSession,
    MenuCategory,
    MenuItem,
    Order,
    OrderItem,
    Restaurant,
    User,
)


def create_user(db: Session, email: str, password: str) -> User:
    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def list_restaurants(db: Session, query: str | None = None) -> list[Restaurant]:
    stmt = db.query(Restaurant).filter(Restaurant.is_active.is_(True))
    if query:
        like = f"%{query.lower()}%"
        stmt = stmt.filter(func.lower(Restaurant.name).like(like))
    return stmt.order_by(Restaurant.name.asc()).all()


def get_restaurant_by_slug_or_id(db: Session, slug_or_id: str) -> Restaurant | None:
    if slug_or_id.isdigit():
        return db.query(Restaurant).filter(Restaurant.id == int(slug_or_id)).first()
    return db.query(Restaurant).filter(Restaurant.slug == slug_or_id).first()


def list_categories(db: Session, restaurant_id: int) -> list[MenuCategory]:
    return (
        db.query(MenuCategory)
        .filter(MenuCategory.restaurant_id == restaurant_id)
        .order_by(MenuCategory.sort_order.asc())
        .all()
    )


def list_items(db: Session, category_id: int) -> list[MenuItem]:
    return (
        db.query(MenuItem)
        .filter(MenuItem.category_id == category_id)
        .filter(MenuItem.is_available.is_(True))
        .order_by(MenuItem.name.asc())
        .all()
    )


def create_chat_session(db: Session, user_id: int) -> ChatSession:
    session = ChatSession(user_id=user_id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def add_chat_message(db: Session, session_id: int, role: str, content: str) -> ChatMessage:
    message = ChatMessage(session_id=session_id, role=role, content=content)
    db.add(message)
    db.commit()
    return message


def create_order(db: Session, user_id: int, restaurant_id: int) -> Order:
    order = Order(user_id=user_id, restaurant_id=restaurant_id, status="pending")
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def get_order(db: Session, order_id: int) -> Order | None:
    return db.query(Order).filter(Order.id == order_id).first()


def attach_order_to_session(db: Session, session: ChatSession, order: Order) -> None:
    session.order_id = order.id
    db.commit()
    db.refresh(session)


def add_order_item(
    db: Session, order: Order, menu_item: MenuItem, quantity: int
) -> OrderItem:
    # Check if this item already exists in the order — if so, increment quantity
    existing = (
        db.query(OrderItem)
        .filter(OrderItem.order_id == order.id, OrderItem.menu_item_id == menu_item.id)
        .first()
    )
    if existing:
        existing.quantity += quantity
        db.commit()
        db.refresh(existing)
        return existing

    item = OrderItem(
        order_id=order.id,
        menu_item_id=menu_item.id,
        quantity=quantity,
        price_cents=menu_item.price_cents,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def recompute_order_total(db: Session, order: Order) -> None:
    total = (
        db.query(func.coalesce(func.sum(OrderItem.price_cents * OrderItem.quantity), 0))
        .filter(OrderItem.order_id == order.id)
        .scalar()
    )
    order.total_cents = int(total or 0)
    db.commit()


def get_user_pending_orders(db: Session, user_id: int) -> list[Order]:
    """Return all pending orders for a user (across all restaurants)."""
    return (
        db.query(Order)
        .filter(Order.user_id == user_id, Order.status == "pending")
        .all()
    )


def get_user_order_for_restaurant(db: Session, user_id: int, restaurant_id: int) -> Order | None:
    """Find existing pending order for a specific restaurant."""
    return (
        db.query(Order)
        .filter(
            Order.user_id == user_id,
            Order.restaurant_id == restaurant_id,
            Order.status == "pending",
        )
        .first()
    )
