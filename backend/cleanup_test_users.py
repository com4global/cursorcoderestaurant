"""One-time script to delete Playwright test users (pw_*@test.com) and their related data."""
from app.db import engine
from sqlalchemy import text

PW_FILTER = "SELECT id FROM users WHERE email LIKE 'pw_%'"

# Ordered from deepest FK children to the users table itself
DELETES = [
    ("chat_messages (user-sessions)", f"DELETE FROM chat_messages WHERE session_id IN (SELECT id FROM chat_sessions WHERE user_id IN ({PW_FILTER}))"),
    ("chat_messages (order-sessions)", f"DELETE FROM chat_messages WHERE session_id IN (SELECT id FROM chat_sessions WHERE order_id IN (SELECT id FROM orders WHERE user_id IN ({PW_FILTER})))"),
    ("chat_sessions (order-linked)", f"DELETE FROM chat_sessions WHERE order_id IN (SELECT id FROM orders WHERE user_id IN ({PW_FILTER}))"),
    ("chat_sessions (user-linked)", f"DELETE FROM chat_sessions WHERE user_id IN ({PW_FILTER})"),
    ("order_feedbacks", f"DELETE FROM order_feedbacks WHERE user_id IN ({PW_FILTER})"),
    ("order_items", f"DELETE FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE user_id IN ({PW_FILTER}))"),
    ("payments", f"DELETE FROM payments WHERE user_id IN ({PW_FILTER})"),
    ("orders", f"DELETE FROM orders WHERE user_id IN ({PW_FILTER})"),
    ("group_order_members", f"DELETE FROM group_order_members WHERE user_id IN ({PW_FILTER})"),
    ("group_order_sessions", f"DELETE FROM group_order_sessions WHERE creator_user_id IN ({PW_FILTER})"),
    ("subscriptions", f"DELETE FROM subscriptions WHERE user_id IN ({PW_FILTER})"),
    ("menu_items", f"DELETE FROM menu_items WHERE category_id IN (SELECT id FROM menu_categories WHERE restaurant_id IN (SELECT id FROM restaurants WHERE owner_id IN ({PW_FILTER})))"),
    ("menu_categories", f"DELETE FROM menu_categories WHERE restaurant_id IN (SELECT id FROM restaurants WHERE owner_id IN ({PW_FILTER}))"),
    ("restaurants", f"DELETE FROM restaurants WHERE owner_id IN ({PW_FILTER})"),
    ("taste_profiles", f"DELETE FROM taste_profiles WHERE user_id IN ({PW_FILTER})"),
    ("users", f"DELETE FROM users WHERE email LIKE 'pw_%'"),
]

with engine.connect() as conn:
    count = conn.execute(text("SELECT COUNT(*) FROM users WHERE email LIKE 'pw_%'")).scalar()
    print(f"Found {count} test users to clean up...")

    for label, sql in DELETES:
        r = conn.execute(text(sql))
        if r.rowcount > 0:
            print(f"  Deleted {r.rowcount} {label}")

    conn.commit()

    remaining = conn.execute(text("SELECT COUNT(*) FROM users WHERE email LIKE 'pw_%'")).scalar()
    total = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
    print(f"\nRemaining pw_* users: {remaining}")
    print(f"Total users in DB: {total}")
    print("Done!")
