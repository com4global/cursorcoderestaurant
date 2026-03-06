# RestarentAI — Implementation Plan

> **Last updated:** 2026-03-05
> **Status:** Phase 2 backend DONE, Phase 2 frontend in progress

---

## What's Built & Working

### Backend (FastAPI + SQLite)
- **Auth**: Register/Login with JWT tokens (`backend/app/auth.py`)
- **Owner Registration**: `POST /auth/register-owner` creates owner role
- **Restaurant API**: `GET /restaurants?lat=X&lng=Y&radius_miles=Z` with Haversine distance filtering
- **Nearby Discovery**: `GET /nearby?lat=X&lng=Y&radius_miles=Z` real restaurants via OpenStreetMap
- **Chat Engine**: Natural language ordering with fuzzy matching (`backend/app/chat.py`)
- **Owner Portal API (Phase 2)**:
  - `GET/POST /owner/restaurants` — list/create restaurants
  - `PUT /owner/restaurants/{id}` — update restaurant
  - `POST /owner/restaurants/{id}/categories` — add category
  - `PUT/DELETE /owner/categories/{id}` — update/remove category
  - `POST /owner/categories/{id}/items` — add menu item
  - `PUT/DELETE /owner/items/{id}` — update/remove item
  - `GET /owner/restaurants/{id}/orders` — view orders
  - `GET /auth/me` — get current user info
- **Models**: User (with role: customer/owner/admin), Restaurant (with owner_id, phone), MenuCategory, MenuItem, Order
- **DB**: Local SQLite (`backend/restarentai.db`)

## Phase 1 — Nearby Restaurant Discovery ✅ DONE

- [x] Auto-detect user location via GPS
- [x] Zipcode lookup via zippopotam.us API
- [x] Radius filtering (5/10/15/25/50 miles)
- [x] Real nearby restaurants from OpenStreetMap Overpass API
- [x] Distance badges + cuisine tags
- [x] # autocomplete shows all nearby restaurants
- [x] Location persisted in localStorage
- **Note:** Google Places key obtained but needs billing. Using free Overpass API for now.

## Phase 2 — Restaurant Onboarding Portal (IN PROGRESS)

**Backend: ✅ DONE**

- [x] Owner role in User model
- [x] `POST /auth/register-owner` endpoint
- [x] Full CRUD for restaurants, categories, items (owner-only)
- [x] Order viewing endpoint
- [x] Ownership validation on all endpoints

**Frontend: ⬜ TODO**

- [ ] Owner dashboard page (separate from customer view)
- [ ] "Register as Restaurant Owner" form
- [ ] Create/edit restaurant form
- [ ] Menu builder: add categories and items
- [ ] Toggle items available/unavailable
- [ ] View incoming orders

---

## Phase 3 — AI Menu Extraction

**Goal:** Use AI to import menus from restaurant websites (one-time, not live scraping).

### Steps:
1. [ ] Admin tool: paste a restaurant's menu URL
2. [ ] Scrape the page content
3. [ ] Send to GPT/Claude to extract structured menu data (categories, items, prices)
4. [ ] Review & confirm extracted data
5. [ ] Import into our database

---

## Phase 4 — Production Deployment

### Steps:
1. [ ] Reconnect Supabase (PostgreSQL) or deploy DB
2. [ ] Deploy backend to Vercel/Railway
3. [ ] Deploy frontend to Netlify/Vercel
4. [ ] Set env variables for production
5. [ ] Payment integration (Stripe)
6. [ ] Real-time order notifications (WebSocket)
7. [ ] SMS/email order confirmations

---

## File Structure
```
restarentAI/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app, routes, CORS
│   │   ├── models.py        # SQLAlchemy models
│   │   ├── schemas.py       # Pydantic schemas
│   │   ├── crud.py          # Database operations
│   │   ├── chat.py          # Chat engine (NLP ordering)
│   │   ├── auth.py          # JWT auth
│   │   ├── config.py        # Settings
│   │   └── db.py            # Database connection
│   ├── .env                 # DATABASE_URL, secrets
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx          # Main app component
│   │   ├── api.js           # API client functions
│   │   ├── styles.css        # All styles
│   │   └── main.jsx         # Entry point
│   └── package.json
├── supabase/
│   └── schema.sql           # Original Supabase schema
└── IMPLEMENTATION_PLAN.md   # THIS FILE
```
