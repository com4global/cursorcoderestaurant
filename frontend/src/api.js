const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    const text = await response.text();
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
