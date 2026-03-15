# 🗺️ RestaurantAI Feature Roadmap

> **Mission**: Build the AI-first restaurant platform that DoorDash and Uber Eats can't replicate.

## Current Features ✅

| Feature | Status |
|---|---|
| AI Chat Ordering (natural language) | ✅ Live |
| Voice Ordering (Sarvam STT/TTS) | ✅ Live |
| Budget Meal Optimizer | ✅ Live |
| Cross-Restaurant Price Compare | ✅ Live |
| Weekly Meal Planner | ✅ Live |
| Intent-Based Search ("spicy under $15") | ✅ Live |
| Menu Auto-Import (URL scraping) | ✅ Live |
| Owner Dashboard + Sales Analytics | ✅ Live |
| Stripe Payments | ✅ Live |
| 327+ automated tests | ✅ Passing |

---

## Upcoming Features — Phased Rollout

### Phase 1: 🔴 Live Kitchen Queue & Real-Time ETA
**Status**: 🟡 Next Up  
**Goal**: Show customers real-time kitchen load — "3 orders ahead • ready in 18 min"

- Owner dashboard: tap-to-update order progress board
- Customer: live progress bar with ETA via WebSocket
- Push status changes: confirmed → preparing → ready → picked up
- Average prep time estimation per restaurant

### Phase 2: 📱 QR Code Scan & Order (Dine-In)
**Status**: ⬜ Planned  
**Goal**: Customers scan a table QR → browse menu → order → food arrives at table

- QR code generator in owner portal (per-table or per-restaurant)
- Dine-in ordering flow (same AI chat, with table context)
- No app download needed (PWA-friendly)
- Opens entirely new market: in-restaurant AI ordering

### Phase 3: 🌍 Multilingual Voice — Tamil & Telugu
**Status**: ⬜ Planned  
**Goal**: Voice ordering in Tamil and Telugu via Sarvam APIs

- Language detection on first utterance
- Route to correct Sarvam language model
- Translate intent → process order in English backend
- Response in customer's chosen language

### Phase 4: 🧠 AI Flavor Profile & Personalized Recommendations
**Status**: ⬜ Planned  
**Goal**: Learn user taste preferences and proactively suggest dishes

- Track order history → build taste vector (spice, protein, cuisine)
- Item tagging system (auto-tag from dish names via AI)
- Personalized ranking: "Based on your love of lamb biryani, try..."
- Explicit preference onboarding ("I like spicy, vegetarian, etc.")

### Phase 5: 💰 Smart Reorder with Price Alerts
**Status**: ⬜ Planned  
**Goal**: Track user's favorite items and notify when prices change

- Frequent order tracking per user
- Price snapshot + diff engine
- Push notification: "Your Chicken Biryani is $2 cheaper at XYZ!"
- One-tap reorder from notification

### Phase 6: 🤖 AI Dietary Assistant — "What Can I Eat?"
**Status**: ⬜ Planned  
**Goal**: Health-aware menu filtering (diabetic, keto, allergies)

- User health profile: goals, restrictions, allergies
- AI-estimated nutrition tagging from dish names
- Per-item badges: ✅ Safe / ⚠️ Caution / ❌ Avoid
- Chat integration: "Show me keto-friendly options under $15"

### Phase 7: 🎯 Group Ordering with AI Consensus
**Status**: ⬜ Planned  
**Goal**: AI finds the optimal restaurant + dishes for a group

- Shareable group session link
- Each member states preferences
- AI consensus engine: satisfy all constraints
- Smart bill splitting

---

## Architecture Principles

1. **AI-first**: Every feature should leverage AI to do something impossible with traditional UI
2. **Test-driven**: Every feature ships with comprehensive backend tests
3. **Mobile-first**: All UI must work beautifully on 390px screens
4. **Real-time**: WebSocket for any live data (kitchen status, group orders)
5. **Incremental**: Each phase is independently shippable and valuable
