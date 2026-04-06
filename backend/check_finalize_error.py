from app.db import SessionLocal
from app import models
import json

db = SessionLocal()
sessions = db.query(models.CallOrderSession).order_by(models.CallOrderSession.id.desc()).limit(5).all()
for s in sessions:
    print(f"Session {s.session_id} - State: {s.state}")
    print(f"  Draft cart: {s.draft_cart_json}")
    
orders = db.query(models.Order).order_by(models.Order.id.desc()).limit(5).all()
for o in orders:
    print(f"Order {o.id} - status: {o.status} - user: {o.user_id} - restaurant: {o.restaurant_id}")
    for i in o.items:
        print(f"  item: {i.menu_item_id} x{i.quantity}")
