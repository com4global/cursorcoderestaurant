import { INTENTS, shouldBypassGlobalSearch, shouldUseDiscoverySearch } from "./IntentParser.js";

export const APP_QUERY_ROUTES = {
  DISCOVERY_SEARCH: "DISCOVERY_SEARCH",
  BROWSE_CATEGORIES: "BROWSE_CATEGORIES",
  BACKEND: "BACKEND",
  RETRY_UNCLEAR: "RETRY_UNCLEAR",
};

export function isMenuBrowseRequest(text) {
  return /today'?s\s+specials?|\bspecials?\b|\bmenu\b|\bmenus\b|\bcategories?\b|\boptions?\b|\bwhat\s+do\s+you\s+have\b|\bshow\s+me\b/i.test(String(text || "").trim());
}

export function isSelectedRestaurantSuggestionRequest(text, intentResult) {
  const normalizedText = String(text || "").trim().toLowerCase();
  if (!normalizedText) return false;

  const entities = intentResult?.entities || {};
  const hasSpecificFoodTarget = Boolean(entities.dish || entities.protein || entities.cuisine);
  const hasSuggestionLanguage = /\b(option|options|suggest|recommend|special|popular|today|something|what\s+should\s+i\s+eat|can\s+you\s+give\s+me|give\s+me\s+some)\b/i.test(normalizedText);
  const hasDirectOrderCommand = /^(?:add|order|get\s+me|i(?:'ll|\s+will)\s+have)\b/i.test(normalizedText);

  return !hasSpecificFoodTarget && hasSuggestionLanguage && !hasDirectOrderCommand;
}

export function decideAppQueryRoute({
  text,
  intentResult,
  selectedRestaurant,
  activeCategories = [],
  restaurants = [],
  fromVoice = false,
}) {
  const normalizedText = String(text || "").trim();
  const hasSelectedContext = Boolean(selectedRestaurant) || activeCategories.length > 0;
  const intent = intentResult?.intent;
  const shouldCompare = shouldUseDiscoverySearch(normalizedText, intentResult);
  const shouldBypass = shouldBypassGlobalSearch(normalizedText, intentResult, restaurants);

  if (!hasSelectedContext) {
    if (intent === INTENTS.NEW_SEARCH && !shouldBypass) {
      return APP_QUERY_ROUTES.DISCOVERY_SEARCH;
    }

    if (shouldCompare && !shouldBypass) {
      return APP_QUERY_ROUTES.DISCOVERY_SEARCH;
    }

    if (intent === INTENTS.UNCLEAR) {
      if (shouldBypass) {
        return APP_QUERY_ROUTES.BACKEND;
      }
      return fromVoice ? APP_QUERY_ROUTES.RETRY_UNCLEAR : APP_QUERY_ROUTES.BACKEND;
    }

    return APP_QUERY_ROUTES.BACKEND;
  }

  if (intent !== INTENTS.MULTI_ORDER && selectedRestaurant && isMenuBrowseRequest(normalizedText) && !shouldUseDiscoverySearch(normalizedText, intentResult)) {
    return APP_QUERY_ROUTES.BROWSE_CATEGORIES;
  }

  return APP_QUERY_ROUTES.BACKEND;
}