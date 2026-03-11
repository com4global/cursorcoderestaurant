"""Stripe payment integration for RestaurantAI.

Handles:
- Owner subscription checkout sessions (Standard $230/mo, Corporate $400/mo)
- Owner free trial activation
- Customer order checkout sessions
- Stripe webhook processing
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import stripe
from dotenv import load_dotenv
from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models

load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_STANDARD_PRICE_ID = os.getenv("STRIPE_STANDARD_PRICE_ID", "")
STRIPE_CORPORATE_PRICE_ID = os.getenv("STRIPE_CORPORATE_PRICE_ID", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

PLAN_PRICE_MAP = {
    "standard": STRIPE_STANDARD_PRICE_ID,
    "corporate": STRIPE_CORPORATE_PRICE_ID,
}

PLAN_AMOUNT_CENTS = {
    "standard": 23000,   # $230
    "corporate": 40000,  # $400
}


# ─── Owner Subscription ───────────────────────────────────────────

def get_or_create_stripe_customer(db: Session, user: models.User) -> str:
    """Get existing Stripe customer ID or create a new one."""
    sub = db.query(models.Subscription).filter(
        models.Subscription.user_id == user.id
    ).first()
    if sub and sub.stripe_customer_id:
        return sub.stripe_customer_id

    customer = stripe.Customer.create(
        email=user.email,
        metadata={"user_id": str(user.id)},
    )
    return customer.id


def start_free_trial(db: Session, user: models.User) -> models.Subscription:
    """Activate a 30-day free trial for an owner. No Stripe required."""
    existing = db.query(models.Subscription).filter(
        models.Subscription.user_id == user.id
    ).first()
    if existing:
        if existing.status in ("active", "trialing"):
            return existing
        # Reactivate canceled subscription as trial
        existing.plan = "free_trial"
        existing.status = "trialing"
        existing.trial_start = datetime.utcnow()
        existing.trial_end = datetime.utcnow() + timedelta(days=30)
        db.commit()
        db.refresh(existing)
        return existing

    sub = models.Subscription(
        user_id=user.id,
        plan="free_trial",
        status="trialing",
        trial_start=datetime.utcnow(),
        trial_end=datetime.utcnow() + timedelta(days=30),
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def create_subscription_checkout(db: Session, user: models.User, plan: str) -> dict:
    """Create a Stripe Checkout Session for an owner subscription."""
    if plan not in PLAN_PRICE_MAP:
        raise HTTPException(status_code=400, detail=f"Invalid plan: {plan}")

    price_id = PLAN_PRICE_MAP[plan]
    if not price_id or price_id.startswith("price_") and "placeholder" in price_id:
        # Stripe not configured — simulate for development
        return _simulate_subscription_checkout(db, user, plan)

    customer_id = get_or_create_stripe_customer(db, user)

    # Save/update customer ID
    sub = db.query(models.Subscription).filter(
        models.Subscription.user_id == user.id
    ).first()
    if sub:
        sub.stripe_customer_id = customer_id
    else:
        sub = models.Subscription(
            user_id=user.id,
            plan=plan,
            status="pending",
            stripe_customer_id=customer_id,
        )
        db.add(sub)
    db.commit()

    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=f"{FRONTEND_URL}?payment=success&plan={plan}",
        cancel_url=f"{FRONTEND_URL}?payment=cancel",
        metadata={"user_id": str(user.id), "plan": plan},
    )

    return {"checkout_url": session.url, "session_id": session.id}


def _simulate_subscription_checkout(db: Session, user: models.User, plan: str) -> dict:
    """Dev-mode: simulate subscription activation without real Stripe."""
    sub = db.query(models.Subscription).filter(
        models.Subscription.user_id == user.id
    ).first()
    now = datetime.utcnow()
    if sub:
        sub.plan = plan
        sub.status = "active"
        sub.current_period_start = now
        sub.current_period_end = now + timedelta(days=30)
    else:
        sub = models.Subscription(
            user_id=user.id,
            plan=plan,
            status="active",
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
        db.add(sub)
    db.commit()
    return {"checkout_url": f"{FRONTEND_URL}?payment=success&plan={plan}", "session_id": "sim_dev"}


def get_subscription(db: Session, user_id: int) -> models.Subscription | None:
    """Get the subscription for a user."""
    return db.query(models.Subscription).filter(
        models.Subscription.user_id == user_id
    ).first()


def is_subscription_active(sub: models.Subscription | None) -> bool:
    """Check if a subscription is currently active or in valid trial."""
    if not sub:
        return False
    now = datetime.utcnow()
    if sub.status == "trialing" and sub.trial_end and sub.trial_end > now:
        return True
    if sub.status == "active":
        return True
    return False


def check_and_expire_trial(db: Session, sub: models.Subscription) -> models.Subscription:
    """If trial has expired, mark it as 'expired' and send notification email."""
    if not sub or sub.status != "trialing":
        return sub
    now = datetime.utcnow()
    if sub.trial_end and sub.trial_end <= now:
        sub.status = "expired"
        db.commit()
        db.refresh(sub)
        # Send expiry email in background
        try:
            _send_trial_expiry_email(db, sub)
        except Exception as e:
            print(f"[Trial] Email send failed: {e}")
    return sub


def get_trial_days_remaining(sub: models.Subscription | None) -> int | None:
    """Get the number of days remaining in a trial."""
    if not sub or sub.status != "trialing" or not sub.trial_end:
        return None
    remaining = (sub.trial_end - datetime.utcnow()).days
    return max(0, remaining)


def _send_trial_expiry_email(db: Session, sub: models.Subscription):
    """Send an email to the owner notifying them their trial has expired."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    user = db.query(models.User).filter(models.User.id == sub.user_id).first()
    if not user:
        return

    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")

    if not smtp_user:
        print(f"[Trial] ⚠️ No SMTP config — skipping expiry email for {user.email}")
        return

    body = f"""Hi {user.email.split('@')[0]},

Your 30-day free trial of RestaurantAI has ended.

To continue using the Owner Dashboard, please upgrade to one of our paid plans:

  📦 Standard — $230/month
     • Unlimited restaurants, priority support, weekly reports

  🏢 Corporate — $400/month
     • Daily sales reports, advanced charts, dedicated account manager

Log in to your Owner Dashboard to upgrade now.

Thank you for trying RestaurantAI!
"""

    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = user.email
        msg["Subject"] = "⏰ Your RestaurantAI Free Trial Has Ended — Upgrade Now"
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, user.email, msg.as_string())
        print(f"[Trial] ✅ Expiry email sent to {user.email}")
    except Exception as e:
        print(f"[Trial] ❌ Email failed for {user.email}: {e}")


def create_billing_portal(db: Session, user: models.User) -> str:
    """Create a Stripe Customer Portal session for managing billing."""
    sub = db.query(models.Subscription).filter(
        models.Subscription.user_id == user.id
    ).first()
    if not sub or not sub.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No active subscription")

    session = stripe.billing_portal.Session.create(
        customer=sub.stripe_customer_id,
        return_url=f"{FRONTEND_URL}?tab=owner",
    )
    return session.url


# ─── Customer Order Checkout ──────────────────────────────────────

def create_order_checkout(db: Session, user: models.User) -> dict:
    """Create a Stripe Checkout Session for all pending cart orders."""
    pending_orders = db.query(models.Order).filter(
        models.Order.user_id == user.id,
        models.Order.status == "pending",
    ).all()

    if not pending_orders:
        raise HTTPException(status_code=400, detail="No items in cart")

    # Build line items from orders
    line_items = []
    total_cents = 0
    order_ids = []
    for order in pending_orders:
        order_ids.append(order.id)
        for oi in order.items:
            mi = db.query(models.MenuItem).filter(
                models.MenuItem.id == oi.menu_item_id
            ).first()
            item_name = mi.name if mi else f"Item #{oi.menu_item_id}"
            line_total = oi.price_cents * oi.quantity
            total_cents += line_total
            line_items.append({
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": item_name},
                    "unit_amount": oi.price_cents,
                },
                "quantity": oi.quantity,
            })

    if not stripe.api_key or stripe.api_key.startswith("sk_test_your"):
        # Dev mode — simulate checkout
        return _simulate_order_checkout(db, user, pending_orders, total_cents)

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=line_items,
        mode="payment",
        success_url=f"{FRONTEND_URL}?payment=order_success&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{FRONTEND_URL}?payment=order_cancel",
        metadata={
            "user_id": str(user.id),
            "order_ids": ",".join(str(oid) for oid in order_ids),
            "type": "order",
        },
    )

    # Record payment
    payment = models.Payment(
        user_id=user.id,
        stripe_checkout_session_id=session.id,
        amount_cents=total_cents,
        status="pending",
        payment_type="order",
    )
    db.add(payment)
    db.commit()

    return {"checkout_url": session.url, "session_id": session.id}


def _simulate_order_checkout(db: Session, user, pending_orders, total_cents) -> dict:
    """Dev-mode: directly confirm orders without real Stripe."""
    from . import models as m

    confirmed = []
    for order in pending_orders:
        order.status = "confirmed"
        db.commit()

        rest = db.query(m.Restaurant).filter(m.Restaurant.id == order.restaurant_id).first()
        items = []
        for oi in order.items:
            mi = db.query(m.MenuItem).filter(m.MenuItem.id == oi.menu_item_id).first()
            items.append({
                "name": mi.name if mi else "?",
                "quantity": oi.quantity,
                "price_cents": oi.price_cents,
            })
        confirmed.append({
            "order_id": order.id,
            "restaurant": rest.name if rest else "?",
            "total_cents": order.total_cents,
            "items": items,
        })

    # Record simulated payment
    payment = models.Payment(
        user_id=user.id,
        amount_cents=total_cents,
        status="completed",
        payment_type="order",
    )
    db.add(payment)
    db.commit()

    return {
        "checkout_url": f"{FRONTEND_URL}?payment=order_success",
        "session_id": "sim_dev",
        "orders": confirmed,
    }


# ─── Stripe Webhook ───────────────────────────────────────────────

def handle_stripe_webhook(payload: bytes, sig_header: str, db: Session):
    """Process Stripe webhook events."""
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(data, db)
    elif event_type == "customer.subscription.updated":
        _handle_subscription_updated(data, db)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(data, db)

    return {"received": True}


def _handle_checkout_completed(session, db: Session):
    """Handle successful checkout — either subscription or order."""
    metadata = session.get("metadata", {})
    payment_type = metadata.get("type", "")

    if session.get("mode") == "subscription":
        # Owner subscription
        user_id = int(metadata.get("user_id", 0))
        plan = metadata.get("plan", "standard")
        stripe_sub_id = session.get("subscription")
        stripe_customer_id = session.get("customer")

        sub = db.query(models.Subscription).filter(
            models.Subscription.user_id == user_id
        ).first()
        now = datetime.utcnow()
        if sub:
            sub.plan = plan
            sub.status = "active"
            sub.stripe_subscription_id = stripe_sub_id
            sub.stripe_customer_id = stripe_customer_id
            sub.current_period_start = now
            sub.current_period_end = now + timedelta(days=30)
        else:
            sub = models.Subscription(
                user_id=user_id,
                plan=plan,
                status="active",
                stripe_subscription_id=stripe_sub_id,
                stripe_customer_id=stripe_customer_id,
                current_period_start=now,
                current_period_end=now + timedelta(days=30),
            )
            db.add(sub)
        db.commit()

    elif payment_type == "order":
        # Customer order payment
        user_id = int(metadata.get("user_id", 0))
        order_ids_str = metadata.get("order_ids", "")
        order_ids = [int(x) for x in order_ids_str.split(",") if x]

        for oid in order_ids:
            order = db.query(models.Order).filter(models.Order.id == oid).first()
            if order and order.status == "pending":
                order.status = "confirmed"
        db.commit()

        # Update payment record
        payment = db.query(models.Payment).filter(
            models.Payment.stripe_checkout_session_id == session.get("id")
        ).first()
        if payment:
            payment.status = "completed"
            payment.stripe_payment_intent_id = session.get("payment_intent")
            db.commit()


def _handle_subscription_updated(subscription_data, db: Session):
    """Handle subscription status changes."""
    stripe_sub_id = subscription_data.get("id")
    sub = db.query(models.Subscription).filter(
        models.Subscription.stripe_subscription_id == stripe_sub_id
    ).first()
    if not sub:
        return

    status = subscription_data.get("status", "")
    if status == "active":
        sub.status = "active"
    elif status == "past_due":
        sub.status = "past_due"
    elif status == "canceled":
        sub.status = "canceled"
    db.commit()


def _handle_subscription_deleted(subscription_data, db: Session):
    """Handle subscription cancellation."""
    stripe_sub_id = subscription_data.get("id")
    sub = db.query(models.Subscription).filter(
        models.Subscription.stripe_subscription_id == stripe_sub_id
    ).first()
    if sub:
        sub.status = "canceled"
        db.commit()
