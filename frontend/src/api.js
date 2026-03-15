// In dev, use same origin so Vite proxy forwards to backend (no CORS); in prod use env or default
const API_BASE = import.meta.env.DEV ? "" : (import.meta.env.VITE_API_BASE || "http://localhost:8000");

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    const text = await response.text();
    if (response.status === 401) {
      const err = new Error("Session expired. Please log in again.");
      err.status = 401;
      throw err;
    }
    throw new Error(text || "Request failed");
  }
  return response.json();
}

export async function register(payload) {
  return request("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function login(payload) {
  return request("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function sendMessage(token, payload) {
  return request("/chat/message", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`
    },
    body: JSON.stringify(payload)
  });
}

export async function listRestaurants({ lat, lng, radius_miles } = {}) {
  const params = new URLSearchParams();
  if (lat != null) params.set("lat", lat);
  if (lng != null) params.set("lng", lng);
  if (radius_miles != null) params.set("radius_miles", radius_miles);
  const qs = params.toString();
  return request(`/restaurants${qs ? "?" + qs : ""}`);
}

export async function searchMenuItems(query) {
  return request(`/search/menu-items?q=${encodeURIComponent(query)}`);
}

/** Fetch menu items for a category (no auth required). Used when guest clicks a category. */
export async function fetchCategoryItems(categoryId) {
  return request(`/categories/${categoryId}/items`);
}

export async function fetchPopularItems() {
  return request(`/search/popular`);
}

export async function searchByIntent(text) {
  return request(`/search/intent`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

export async function generateMealPlan(text) {
  return request(`/mealplan/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

export async function swapMeal({ text, day_index, current_item_id, budget_remaining_cents }) {
  return request(`/mealplan/swap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, day_index, current_item_id, budget_remaining_cents }),
  });
}

export async function fetchNearby({ lat, lng, radius_miles } = {}) {
  const params = new URLSearchParams();
  if (lat != null) params.set("lat", lat);
  if (lng != null) params.set("lng", lng);
  if (radius_miles != null) params.set("radius_miles", radius_miles);
  const qs = params.toString();
  return request(`/nearby?${qs}`);
}

// --- Owner Portal APIs ---

export async function registerOwner(payload) {
  return request("/auth/register-owner", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function getMe(token) {
  return request("/auth/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function getMyRestaurants(token) {
  return request("/owner/restaurants", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function createRestaurant(token, payload) {
  return request("/owner/restaurants", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  });
}

export async function importMenuFromUrl(token, url) {
  // Menu extraction is slow (30-90s): Playwright rendering + AI extraction
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 180000); // 3 minute timeout
  try {
    const resp = await fetch(`${API_BASE}/owner/import-menu`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ url }),
      signal: controller.signal,
    });
    clearTimeout(timeout);
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(text || "Import failed");
    }
    return resp.json();
  } catch (err) {
    clearTimeout(timeout);
    if (err.name === 'AbortError') {
      throw new Error("Menu extraction timed out. The website may be too complex. Try a simpler menu page URL.");
    }
    throw err;
  }
}

export async function extractMenuFromFile(token, restaurantId, file) {
  const formData = new FormData();
  formData.append("file", file);
  return request(`/owner/restaurants/${restaurantId}/extract-menu-file`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });
}

export async function saveImportedMenu(token, restaurantId, menuData) {
  return request(`/owner/restaurants/${restaurantId}/import-menu`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(menuData),
  });
}

export async function fetchCart(token) {
  return request("/cart", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function addComboToCart(token, restaurantId, items) {
  return request("/cart/add-combo", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ restaurant_id: restaurantId, items }),
  });
}

export async function removeCartItem(token, orderItemId) {
  return request(`/cart/item/${orderItemId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function clearCart(token) {
  return request("/cart/clear", {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
}

// --- Order Management APIs ---

export async function fetchOrders(token, restaurantId, { search, dateFrom, dateTo } = {}) {
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  const qs = params.toString() ? `?${params.toString()}` : "";
  return request(`/owner/restaurants/${restaurantId}/orders${qs}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function fetchArchivedOrders(token, restaurantId, page = 1, { search, dateFrom, dateTo } = {}) {
  const params = new URLSearchParams({ page: String(page) });
  if (search) params.set("search", search);
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  return request(`/owner/restaurants/${restaurantId}/orders/archived?${params.toString()}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function fetchAnalytics(token, restaurantId, period = "month", dateFrom, dateTo) {
  const params = new URLSearchParams({ period });
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  return request(`/owner/restaurants/${restaurantId}/analytics?${params.toString()}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function updateOrderStatus(token, orderId, status) {
  return request(`/owner/orders/${orderId}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ status }),
  });
}

export async function fetchComplaints(token, restaurantId) {
  return request(`/owner/restaurants/${restaurantId}/complaints`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function checkout(token) {
  return request("/checkout", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function updateNotifications(token, restaurantId, payload) {
  return request(`/owner/restaurants/${restaurantId}/notifications`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  });
}

export async function fetchMyOrders(token) {
  return request("/my-orders", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

// --- Post-Order Feedback ---
export async function submitFeedback(token, payload) {
  return request("/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  });
}

// --- Taste Profile (AI Flavor / Recommendations) ---

export async function getTasteProfile(token) {
  return request("/taste/profile", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function updateTasteProfile(token, payload) {
  return request("/taste/profile", {
    method: "PUT",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  });
}

export async function getTasteHistorySummary(token) {
  return request("/taste/history-summary", { headers: { Authorization: `Bearer ${token}` } });
}

export async function getTasteRecommendations(token, limit = 10) {
  return request(`/taste/recommendations?limit=${limit}`, { headers: { Authorization: `Bearer ${token}` } });
}

// --- Sarvam AI Voice APIs ---

export async function voiceSTT(audioBlob) {
  const formData = new FormData();
  formData.append("file", audioBlob, "audio.webm");
  const resp = await fetch(`${API_BASE}/api/voice/stt`, {
    method: "POST",
    body: formData,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text || "STT failed");
  }
  return resp.json(); // { transcript, language }
}

export async function voiceTTS(text, language = "en-IN", speaker = "kavya") {
  const resp = await fetch(`${API_BASE}/api/voice/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, language, speaker }),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text || "TTS failed");
  }
  return resp.json(); // { audio_base64, format }
}

export async function voiceChat(message, context = "") {
  const resp = await fetch(`${API_BASE}/api/voice/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, context }),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text || "Chat failed");
  }
  return resp.json(); // { reply }
}

// --- Payment APIs ---

export async function startOwnerTrial(token) {
  return request("/owner/start-trial", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function createOwnerSubscription(token, plan) {
  return request("/owner/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ plan }),
  });
}

export async function getOwnerSubscription(token) {
  return request("/owner/subscription", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function getManageBillingUrl(token) {
  return request("/owner/manage-billing", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function createCheckoutSession(token) {
  return request("/checkout/create-session", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function verifyPayment(token, sessionId) {
  return request("/checkout/verify", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
}

// --- Order Tracking & Kitchen Queue ---

export async function trackOrder(token, orderId) {
  return request(`/orders/${orderId}/track`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function getRestaurantQueue(restaurantId) {
  return request(`/restaurant/${restaurantId}/queue`);
}

// --- AI Budget Optimizer ---

export async function mealOptimizer({ people, budgetCents, cuisine, restaurantId } = {}) {
  const body = { people, budget_cents: budgetCents };
  if (cuisine) body.cuisine = cuisine;
  if (restaurantId) body.restaurant_id = restaurantId;
  return request("/ai/meal-optimizer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// --- Group Ordering ---

/** Create a group order session. Auth optional. Returns { id, share_code, members, ... }. */
export async function createGroupSession(tokenOrNull, payload = {}) {
  const opts = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  };
  if (tokenOrNull) opts.headers.Authorization = `Bearer ${tokenOrNull}`;
  return request("/group/session", opts);
}

/** Get group session by id or share code. No auth. */
export async function getGroupSession(groupIdOrCode) {
  return request(`/group/${encodeURIComponent(groupIdOrCode)}`);
}

/** Join a group: add member (name, preference, budget_cents, dietary_restrictions). Auth optional. */
export async function joinGroupSession(groupIdOrCode, payload, tokenOrNull = null) {
  const opts = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  };
  if (tokenOrNull) opts.headers.Authorization = `Bearer ${tokenOrNull}`;
  return request(`/group/${encodeURIComponent(groupIdOrCode)}/join`, opts);
}

/** Get AI recommendation for the group (restaurant + suggested dishes). Optional: restaurantIds (array), cuisine to narrow results. */
export async function getGroupRecommendation(groupIdOrCode, { lat, lng, restaurantIds, cuisine } = {}) {
  const params = new URLSearchParams();
  if (lat != null) params.set("lat", lat);
  if (lng != null) params.set("lng", lng);
  if (restaurantIds && restaurantIds.length > 0) params.set("restaurant_ids", restaurantIds.join(","));
  if (cuisine && String(cuisine).trim()) params.set("cuisine", String(cuisine).trim());
  const qs = params.toString() ? `?${params.toString()}` : "";
  return request(`/group/${encodeURIComponent(groupIdOrCode)}/recommendation${qs}`);
}

/** Get equal bill split. */
export async function getGroupSplitEqual(groupIdOrCode, totalCents, deliveryCents = 0, taxCents = 0) {
  const params = new URLSearchParams({
    total_cents: String(totalCents),
    delivery_cents: String(deliveryCents),
    tax_cents: String(taxCents),
    mode: "equal",
  });
  return request(`/group/${encodeURIComponent(groupIdOrCode)}/split?${params.toString()}`);
}

/** Get item-based bill split. */
export async function postGroupSplitItemBased(groupIdOrCode, { totalCents, deliveryCents = 0, taxCents = 0, memberItemCents }) {
  return request(`/group/${encodeURIComponent(groupIdOrCode)}/split`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      total_cents: totalCents,
      delivery_cents: deliveryCents,
      tax_cents: taxCents,
      mode: "item",
      member_item_cents: memberItemCents,
    }),
  });
}
