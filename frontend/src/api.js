const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

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
  return request("/owner/import-menu", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ url }),
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

// --- Sarvam AI Voice APIs ---

export async function voiceSTT(audioBlob) {
  const formData = new FormData();
  formData.append("file", audioBlob, "audio.webm");
  const API = import.meta.env.VITE_API_BASE || "http://localhost:8000";
  const resp = await fetch(`${API}/api/voice/stt`, {
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
  const API = import.meta.env.VITE_API_BASE || "http://localhost:8000";
  const resp = await fetch(`${API}/api/voice/tts`, {
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
  const API = import.meta.env.VITE_API_BASE || "http://localhost:8000";
  const resp = await fetch(`${API}/api/voice/chat`, {
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
