import { describe, expect, it } from "vitest";

import { INTENTS, parseIntent } from "./IntentParser.js";
import { APP_QUERY_ROUTES, decideAppQueryRoute, isSelectedRestaurantSuggestionRequest } from "./queryRouting.js";

const RESTAURANTS = [
  { id: 1, name: "Aroma Biryani", slug: "aroma-biryani" },
  { id: 2, name: "DC District", slug: "dc-district" },
  { id: 3, name: "Anjappar", slug: "anjappar" },
];

const ACTIVE_CATEGORIES = [
  { id: 10, name: "Today's Specials" },
  { id: 11, name: "Biryani" },
  { id: 12, name: "Soups" },
];

describe("decideAppQueryRoute", () => {
  it("routes cheap nearby discovery queries to discovery search", () => {
    const input = "cheap biryani nearby";
    const intentResult = parseIntent(input, {}, RESTAURANTS);

    expect(decideAppQueryRoute({
      text: input,
      intentResult,
      selectedRestaurant: null,
      activeCategories: [],
      restaurants: RESTAURANTS,
    })).toBe(APP_QUERY_ROUTES.DISCOVERY_SEARCH);
  });

  it("routes plain global dish searches to discovery search", () => {
    const input = "biryani";
    const intentResult = parseIntent(input, {}, RESTAURANTS);

    expect(decideAppQueryRoute({
      text: input,
      intentResult,
      selectedRestaurant: null,
      activeCategories: [],
      restaurants: RESTAURANTS,
    })).toBe(APP_QUERY_ROUTES.DISCOVERY_SEARCH);
  });

  it("routes misspelled global dish searches to discovery search", () => {
    const input = "briyani";
    const intentResult = parseIntent(input, {}, RESTAURANTS);

    expect(decideAppQueryRoute({
      text: input,
      intentResult,
      selectedRestaurant: null,
      activeCategories: [],
      restaurants: RESTAURANTS,
    })).toBe(APP_QUERY_ROUTES.DISCOVERY_SEARCH);
  });

  it("routes hybrid special-item nearby suggestions to discovery search", () => {
    const input = "give me something special item near by ?";
    const intentResult = parseIntent(input, {}, RESTAURANTS);

    expect([INTENTS.UNCLEAR, INTENTS.NEW_SEARCH]).toContain(intentResult.intent);
    expect(decideAppQueryRoute({
      text: input,
      intentResult,
      selectedRestaurant: null,
      activeCategories: [],
      restaurants: RESTAURANTS,
    })).toBe(APP_QUERY_ROUTES.DISCOVERY_SEARCH);
  });

  it("routes vague combo suggestion requests to discovery search", () => {
    const input = "give me some special combos today";
    const intentResult = parseIntent(input, {}, RESTAURANTS);

    expect(decideAppQueryRoute({
      text: input,
      intentResult,
      selectedRestaurant: null,
      activeCategories: [],
      restaurants: RESTAURANTS,
    })).toBe(APP_QUERY_ROUTES.DISCOVERY_SEARCH);
  });

  it("routes browse-style specials requests to category browsing when a menu is open", () => {
    const input = "show me today's specials";
    const intentResult = parseIntent(input, {}, RESTAURANTS);

    expect(decideAppQueryRoute({
      text: input,
      intentResult,
      selectedRestaurant: RESTAURANTS[0],
      activeCategories: ACTIVE_CATEGORIES,
      restaurants: RESTAURANTS,
    })).toBe(APP_QUERY_ROUTES.BROWSE_CATEGORIES);
  });

  it("routes browse-style specials requests to category browsing when a restaurant is selected but categories are not loaded yet", () => {
    const input = "show me today's specials";
    const intentResult = parseIntent(input, {}, RESTAURANTS);

    expect(decideAppQueryRoute({
      text: input,
      intentResult,
      selectedRestaurant: RESTAURANTS[0],
      activeCategories: [],
      restaurants: RESTAURANTS,
    })).toBe(APP_QUERY_ROUTES.BROWSE_CATEGORIES);
  });

  it("routes todays special menus phrasing to category browsing when a menu is open", () => {
    const input = "give me some today's special menus";
    const intentResult = parseIntent(input, {}, RESTAURANTS);

    expect(decideAppQueryRoute({
      text: input,
      intentResult,
      selectedRestaurant: RESTAURANTS[0],
      activeCategories: ACTIVE_CATEGORIES,
      restaurants: RESTAURANTS,
    })).toBe(APP_QUERY_ROUTES.BROWSE_CATEGORIES);
  });

  it("detects vague spicy special-item option requests inside a selected restaurant context", () => {
    const input = "I want some special spicy item today can you give me some option";
    const intentResult = parseIntent(input, {}, RESTAURANTS);

    expect(intentResult.intent).toBe(INTENTS.UNCLEAR);
    expect(isSelectedRestaurantSuggestionRequest(input, intentResult)).toBe(true);
  });

  it("detects best spicy options phrasing inside a selected restaurant context", () => {
    const input = "show me best spicy options here";
    const intentResult = parseIntent(input, {}, RESTAURANTS);

    expect(isSelectedRestaurantSuggestionRequest(input, intentResult)).toBe(true);
  });

  it("detects recommendation phrasing inside a selected restaurant context", () => {
    const input = "recommend something special here";
    const intentResult = parseIntent(input, {}, RESTAURANTS);

    expect(isSelectedRestaurantSuggestionRequest(input, intentResult)).toBe(true);
  });

  it("detects what spicy item do you have today phrasing inside a selected restaurant context", () => {
    const input = "what spicy item do you have today";
    const intentResult = parseIntent(input, {}, RESTAURANTS);

    expect(isSelectedRestaurantSuggestionRequest(input, intentResult)).toBe(true);
  });

  it("does not treat direct add-to-cart phrasing as a suggestion request", () => {
    const input = "add one spicy chicken lollipop";
    const intentResult = parseIntent(input, {}, RESTAURANTS);

    expect(isSelectedRestaurantSuggestionRequest(input, intentResult)).toBe(false);
  });

  it("does not treat specific dish search phrasing as a suggestion request", () => {
    const input = "show me spicy soup";
    const intentResult = parseIntent(input, {}, RESTAURANTS);

    expect(intentResult.entities.dish).toBe("soup");
    expect(isSelectedRestaurantSuggestionRequest(input, intentResult)).toBe(false);
  });

  it("routes mixed-language direct order text to backend instead of discovery", () => {
    const input = "எனக்கு chicken biryani aroma restaurantல் வேண்டும்";
    const intentResult = parseIntent(input, {}, RESTAURANTS);

    expect(decideAppQueryRoute({
      text: input,
      intentResult,
      selectedRestaurant: null,
      activeCategories: [],
      restaurants: RESTAURANTS,
    })).toBe(APP_QUERY_ROUTES.BACKEND);
  });

  it("asks voice users to retry on non-discovery unclear input", () => {
    const input = "xkcd fjdsla";
    const intentResult = parseIntent(input, {}, RESTAURANTS);

    expect(intentResult.intent).toBe(INTENTS.UNCLEAR);
    expect(decideAppQueryRoute({
      text: input,
      intentResult,
      selectedRestaurant: null,
      activeCategories: [],
      restaurants: RESTAURANTS,
      fromVoice: true,
    })).toBe(APP_QUERY_ROUTES.RETRY_UNCLEAR);
  });
});