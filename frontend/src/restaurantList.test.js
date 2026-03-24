import { describe, expect, it } from "vitest";

import { dedupeRestaurants } from "./restaurantList.js";

describe("dedupeRestaurants", () => {
  it("removes exact duplicate restaurant cards by normalized name and location", () => {
    const input = [
      { id: 1, name: "Order Test Rest", city: "TestCity" },
      { id: 2, name: "Order Test Rest", city: "TestCity" },
      { id: 3, name: "Another Rest", city: "TestCity" },
    ];

    const result = dedupeRestaurants(input);
    expect(result).toHaveLength(2);
    expect(result.map((restaurant) => restaurant.name)).toEqual(["Order Test Rest", "Another Rest"]);
  });

  it("keeps same-name restaurants in different cities", () => {
    const input = [
      { id: 1, name: "Spice Garden", city: "Dallas" },
      { id: 2, name: "Spice Garden", city: "Austin" },
    ];

    const result = dedupeRestaurants(input);
    expect(result).toHaveLength(2);
  });

  it("prefers the richer record when duplicates exist", () => {
    const input = [
      { id: 1, name: "Aroma", city: "Plano" },
      { id: 2, name: "Aroma", city: "Plano", address: "123 Main St", rating: 4.6 },
    ];

    const result = dedupeRestaurants(input);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe(2);
  });
});