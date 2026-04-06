/**
 * Voice matching tests: ensure category and item names (as would be spoken)
 * match the correct category/item. Run against all restaurants/categories/items
 * when backend is up: npm run test:voice:live (set VOICE_TEST_API_BASE if not localhost:8000).
 */
import { describe, it, expect, beforeAll } from "vitest";
import { matchCategory, matchItem } from "./voiceMatch.js";

// ---- Unit tests (no API) ----
describe("matchCategory", () => {
  const categories = [
    { id: 18, name: "Breads" },
    { id: 20, name: "Desi Burgers" },
    { id: 55, name: "Coffee" },
    { id: 9, name: "Snacks" },
    { id: 12, name: "Buy 1 Get 1 Deals" },
    { id: 77, name: "Today's Specials" },
  ];

  it("matches exact category name", () => {
    expect(matchCategory(categories, "Desi Burgers")?.id).toBe(20);
    expect(matchCategory(categories, "Coffee")?.id).toBe(55);
    expect(matchCategory(categories, "Snacks")?.id).toBe(9);
  });

  it("matches with 'one' normalized to '1' (Buy 1 Get 1 Deals)", () => {
    expect(matchCategory(categories, "buy one get one deals")?.id).toBe(12);
    expect(matchCategory(categories, "Buy one get one deals")?.id).toBe(12);
  });

  it("matches single word that identifies category", () => {
    expect(matchCategory(categories, "burgers")?.id).toBe(20);
    expect(matchCategory(categories, "breads")?.id).toBe(18);
    expect(matchCategory(categories, "snacks")?.id).toBe(9);
  });

  it("does not match 'fix' to Coffee", () => {
    expect(matchCategory(categories, "fix")).toBeNull();
  });

  it("does not match when input is much longer than category (e.g. phrase containing category)", () => {
    // "let's see burgers" should match Desi Burgers via word "burgers", not Coffee
    const matched = matchCategory(categories, "let's see burgers");
    expect(matched?.id).toBe(20);
  });

  it("matches menu-browse phrasing to today's specials category", () => {
    expect(matchCategory(categories, "give me some today's special menus")?.id).toBe(77);
    expect(matchCategory(categories, "show me today's specials menu")?.id).toBe(77);
  });

  it("matches additional browse phrasing to today's specials category", () => {
    expect(matchCategory(categories, "what do you have in today's specials")?.id).toBe(77);
    expect(matchCategory(categories, "browse today's specials options")?.id).toBe(77);
  });

  it("returns null for empty or no match", () => {
    expect(matchCategory(categories, "")).toBeNull();
    expect(matchCategory(categories, "xyz unknown")).toBeNull();
    expect(matchCategory([], "Coffee")).toBeNull();
  });
});

describe("matchItem", () => {
  const items = [
    { id: 34, name: "Masala Vada (4 Pcs)" },
    { id: 1, name: "Filter Coffee" },
    { id: 2, name: "Cold Coffee" },
  ];

  it("matches exact item name", () => {
    expect(matchItem(items, "Masala Vada (4 Pcs)")?.id).toBe(34);
    expect(matchItem(items, "Filter Coffee")?.id).toBe(1);
  });

  it("matches with add/i want prefix stripped", () => {
    expect(matchItem(items, "add Masala Vada")?.id).toBe(34);
    expect(matchItem(items, "I want filter coffee")?.id).toBe(1);
  });

  it("matches partial / spoken form (Masala weather -> Masala Vada)", () => {
    const m = matchItem(items, "Masala weather");
    expect(m?.id).toBe(34);
  });

  it("returns null for no match", () => {
    expect(matchItem(items, "unknown item")).toBeNull();
    expect(matchItem([], "Filter Coffee")).toBeNull();
  });
});

// ---- Live tests: run against all restaurants/categories/items from API ----
const LIVE = process.env.VOICE_TEST_LIVE === "1" || process.env.VOICE_TEST_LIVE === "true";
const API_BASE = process.env.VOICE_TEST_API_BASE || process.env.VITE_API_BASE || "http://localhost:8000";

async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${path} ${res.status}`);
  return res.json();
}

describe.runIf(LIVE)("voice match — all restaurants/categories/items (live API)", () => {
  /** @type {{ id: number, name: string, slug?: string }[]} */
  let restaurants = [];
  /** @type {{ restaurantId: number, categories: { id: number, name: string }[], itemsByCategory: Map<number, { id: number, name: string }[]> }} */
  const menuByRestaurant = new Map();

  beforeAll(async () => {
    restaurants = await apiGet("/restaurants");
    if (!Array.isArray(restaurants) || restaurants.length === 0) {
      console.warn("No restaurants returned from API; skipping live voice tests.");
      return;
    }
    for (const rest of restaurants) {
      const id = rest.id ?? rest.restaurant_id;
      if (id == null) continue;
      let categories = [];
      try {
        categories = await apiGet(`/restaurants/${id}/categories`);
      } catch (e) {
        continue;
      }
      if (!Array.isArray(categories)) categories = [];
      const itemsByCategory = new Map();
      for (const cat of categories) {
        try {
          const items = await apiGet(`/categories/${cat.id}/items`);
          itemsByCategory.set(cat.id, Array.isArray(items) ? items : []);
        } catch (_) {
          itemsByCategory.set(cat.id, []);
        }
      }
      menuByRestaurant.set(id, { categories, itemsByCategory });
    }
  }, 120000);

  it("every category name matches itself when spoken", async () => {
    let failed = [];
    for (const rest of restaurants) {
      const id = rest.id ?? rest.restaurant_id;
      const data = menuByRestaurant.get(id);
      if (!data?.categories?.length) continue;
      for (const cat of data.categories) {
        const name = typeof cat.name === "string" ? cat.name : cat?.name?.name ?? cat?.name ?? "";
        if (!name) continue;
        const matched = matchCategory(data.categories, name);
        if (!matched || matched.id !== cat.id) {
          failed.push({ restaurant: rest.name, category: name, expectedId: cat.id, matched: matched?.name ?? null });
        }
      }
    }
    expect(failed).toEqual([]);
  });

  it("every item name matches itself when spoken (within its category)", async () => {
    let failed = [];
    for (const rest of restaurants) {
      const id = rest.id ?? rest.restaurant_id;
      const data = menuByRestaurant.get(id);
      if (!data) continue;
      for (const cat of data.categories) {
        const items = data.itemsByCategory.get(cat.id) || [];
        for (const item of items) {
          const name = typeof item.name === "string" ? item.name : item?.name ?? "";
          if (!name) continue;
          const matched = matchItem(items, name);
          if (!matched || matched.id !== item.id) {
            failed.push({
              restaurant: rest.name,
              category: cat.name,
              item: name,
              expectedId: item.id,
              matched: matched?.name ?? null,
            });
          }
        }
      }
    }
    expect(failed).toEqual([]);
  });

  it("category name variants (e.g. 'buy one get one deals') match correct category", async () => {
    let failed = [];
    for (const rest of restaurants) {
      const id = rest.id ?? rest.restaurant_id;
      const data = menuByRestaurant.get(id);
      if (!data?.categories?.length) continue;
      for (const cat of data.categories) {
        const name = typeof cat.name === "string" ? cat.name : cat?.name?.name ?? cat?.name ?? "";
        if (!name) continue;
        const variant = name.replace(/\s*1\s*/gi, " one ");
        if (variant === name) continue;
        const matched = matchCategory(data.categories, variant);
        if (!matched || matched.id !== cat.id) {
          failed.push({ restaurant: rest.name, category: name, variant, expectedId: cat.id, matched: matched?.name ?? null });
        }
      }
    }
    expect(failed).toEqual([]);
  });
});
