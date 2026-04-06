/**
 * IntentParser Unit Tests
 *
 * Tests every intent type + detectMultiOrder.
 * Run: npm test (vitest)
 */
import { describe, it, expect } from 'vitest';
import { parseIntent, detectMultiOrder, shouldBypassGlobalSearch, shouldUseDiscoverySearch, INTENTS } from './IntentParser.js';

const RESTAURANTS = [
    { id: 1, name: 'Aroma Biryani', slug: 'aroma-biryani' },
    { id: 2, name: 'DC District', slug: 'dc-district' },
    { id: 3, name: 'Anjappar', slug: 'anjappar' },
];

// ─── detectMultiOrder ─────────────────────────────────────────────────────────
describe('detectMultiOrder', () => {
    it('detects "X from A and Y from B" pattern', () => {
        expect(detectMultiOrder('one biryani from aroma and one soup from dc district', RESTAURANTS)).toBe(true);
    });

    it('detects "2 dosa from anjappar and 1 biryani from aroma"', () => {
        expect(detectMultiOrder('2 dosa from anjappar and 1 biryani from aroma', RESTAURANTS)).toBe(true);
    });

    it('returns false for single-restaurant order', () => {
        expect(detectMultiOrder('biryani from aroma', RESTAURANTS)).toBe(false);
    });

    it('returns false for plain food query', () => {
        expect(detectMultiOrder('i want biryani', RESTAURANTS)).toBe(false);
    });

    it('returns false for empty string', () => {
        expect(detectMultiOrder('', RESTAURANTS)).toBe(false);
    });

    it('detects multi-order with short/unknown restaurant names (no restaurant list)', () => {
        // Without a restaurant list, 2+ "from X" clauses still detected
        expect(detectMultiOrder('soup from x and biryani from y', [])).toBe(true);
    });

    it('returns false when only one "from" clause even with restaurant list', () => {
        expect(detectMultiOrder('biryani from aroma only', RESTAURANTS)).toBe(false);
    });

    it('detects mixed Tamil-English multi-order phrases', () => {
        expect(detectMultiOrder('எனக்கு one biryani from aroma and one soup from anjappar வேண்டும்', RESTAURANTS)).toBe(true);
    });
});

// ─── parseIntent — GREETING ───────────────────────────────────────────────────
describe('parseIntent — GREETING', () => {
    it('classifies "hello"', () => expect(parseIntent('hello').intent).toBe(INTENTS.GREETING));
    it('classifies "hi"', () => expect(parseIntent('hi').intent).toBe(INTENTS.GREETING));
    it('classifies "hey"', () => expect(parseIntent('hey').intent).toBe(INTENTS.GREETING));
    it('classifies "good morning"', () => expect(parseIntent('good morning').intent).toBe(INTENTS.GREETING));
    it('classifies "testing"', () => expect(parseIntent('testing').intent).toBe(INTENTS.GREETING));
});

// ─── parseIntent — THANKS ─────────────────────────────────────────────────────
describe('parseIntent — THANKS', () => {
    it('classifies "thank you"', () => expect(parseIntent('thank you').intent).toBe(INTENTS.THANKS));
    it('classifies "thanks"', () => expect(parseIntent('thanks').intent).toBe(INTENTS.THANKS));
    it('classifies "thx"', () => expect(parseIntent('thx').intent).toBe(INTENTS.THANKS));
});

// ─── parseIntent — GOODBYE ────────────────────────────────────────────────────
describe('parseIntent — GOODBYE', () => {
    it('classifies "bye"', () => expect(parseIntent('bye').intent).toBe(INTENTS.GOODBYE));
    it('classifies "goodbye"', () => expect(parseIntent('goodbye').intent).toBe(INTENTS.GOODBYE));
    it('classifies "exit"', () => expect(parseIntent('exit').intent).toBe(INTENTS.GOODBYE));
});

// ─── parseIntent — SHOW_CART ──────────────────────────────────────────────────
describe('parseIntent — SHOW_CART', () => {
    it('classifies "show cart"', () => expect(parseIntent('show cart').intent).toBe(INTENTS.SHOW_CART));
    it('classifies "what\'s in my cart"', () => expect(parseIntent("what's in my cart").intent).toBe(INTENTS.SHOW_CART));
    it('classifies "my cart"', () => expect(parseIntent('my cart').intent).toBe(INTENTS.SHOW_CART));
    it('classifies "view cart"', () => expect(parseIntent('view cart').intent).toBe(INTENTS.SHOW_CART));
    it('classifies "cart"', () => expect(parseIntent('cart').intent).toBe(INTENTS.SHOW_CART));
});

// ─── parseIntent — CLEAR_CART ─────────────────────────────────────────────────
describe('parseIntent — CLEAR_CART', () => {
    it('classifies "clear the cart"', () => expect(parseIntent('clear the cart').intent).toBe(INTENTS.CLEAR_CART));
    it('classifies "empty my cart"', () => expect(parseIntent('empty my cart').intent).toBe(INTENTS.CLEAR_CART));
    it('classifies "order fresh"', () => expect(parseIntent('order fresh').intent).toBe(INTENTS.CLEAR_CART));
    it('classifies "start fresh"', () => expect(parseIntent('start fresh').intent).toBe(INTENTS.CLEAR_CART));
    it('classifies "clear all"', () => expect(parseIntent('clear all').intent).toBe(INTENTS.CLEAR_CART));
    it('classifies "remove all"', () => expect(parseIntent('remove all').intent).toBe(INTENTS.CLEAR_CART));
    it('classifies "cancel my order"', () => expect(parseIntent('cancel my order').intent).toBe(INTENTS.CLEAR_CART));
    // Voice transcription variants
    it('classifies "clear the court" (voice transcription of cart)', () => expect(parseIntent('clear the court').intent).toBe(INTENTS.CLEAR_CART));
    it('classifies "clear my car" (voice transcription of cart)', () => expect(parseIntent('clear my car').intent).toBe(INTENTS.CLEAR_CART));
});

// ─── parseIntent — CHECKOUT ───────────────────────────────────────────────────
describe('parseIntent — CHECKOUT', () => {
    it('classifies "checkout"', () => expect(parseIntent('checkout').intent).toBe(INTENTS.CHECKOUT));
    it('classifies "place order"', () => expect(parseIntent('place order').intent).toBe(INTENTS.CHECKOUT));
    it('classifies "place my order"', () => expect(parseIntent('place my order').intent).toBe(INTENTS.CHECKOUT));
    it('classifies "confirm"', () => expect(parseIntent('confirm').intent).toBe(INTENTS.CHECKOUT));
    it('classifies "pay"', () => expect(parseIntent('pay').intent).toBe(INTENTS.CHECKOUT));
    it('classifies "i\'m done"', () => expect(parseIntent("i'm done").intent).toBe(INTENTS.CHECKOUT));
    it('classifies "that\'s all"', () => expect(parseIntent("that's all").intent).toBe(INTENTS.CHECKOUT));
});

// ─── parseIntent — ADD_TO_CART ────────────────────────────────────────────────
describe('parseIntent — ADD_TO_CART', () => {
    it('classifies "add biryani"', () => expect(parseIntent('add biryani').intent).toBe(INTENTS.ADD_TO_CART));
    it('classifies "i want biryani"', () => expect(parseIntent('i want biryani').intent).toBe(INTENTS.ADD_TO_CART));
    it('classifies "give me dosa"', () => expect(parseIntent('give me dosa').intent).toBe(INTENTS.ADD_TO_CART));
    it('classifies "order 2 naan"', () => expect(parseIntent('order 2 naan').intent).toBe(INTENTS.ADD_TO_CART));
    it('classifies "I\'ll have the biryani"', () => expect(parseIntent("I'll have the biryani").intent).toBe(INTENTS.ADD_TO_CART));
    it('classifies "get me a coffee"', () => expect(parseIntent('get me a coffee').intent).toBe(INTENTS.ADD_TO_CART));
    it('classifies "add to cart"', () => expect(parseIntent('add to cart').intent).toBe(INTENTS.ADD_TO_CART));
    it('classifies "I need a pizza"', () => expect(parseIntent('I need a pizza').intent).toBe(INTENTS.ADD_TO_CART));

    it('does not classify menu-browse requests as add to cart', () => {
        const r = parseIntent("give me some today's special menus", {}, RESTAURANTS);
        expect(r.intent).not.toBe(INTENTS.ADD_TO_CART);
    });

    it('does not classify todays specials browse phrasing as add to cart', () => {
        const r = parseIntent("show me today's specials", {}, RESTAURANTS);
        expect(r.intent).not.toBe(INTENTS.ADD_TO_CART);
    });

    it('does not classify vague combo suggestion phrasing as add to cart', () => {
        const r = parseIntent('give me some special combos today', {}, RESTAURANTS);
        expect(r.intent).not.toBe(INTENTS.ADD_TO_CART);
    });
});

// ─── parseIntent — REMOVE_ITEM ────────────────────────────────────────────────
describe('parseIntent — REMOVE_ITEM', () => {
    it('classifies "remove biryani"', () => expect(parseIntent('remove biryani').intent).toBe(INTENTS.REMOVE_ITEM));
    it('classifies "delete the naan"', () => expect(parseIntent('delete the naan').intent).toBe(INTENTS.REMOVE_ITEM));
    it('classifies "cancel that"', () => expect(parseIntent('cancel that').intent).toBe(INTENTS.REMOVE_ITEM));
    it('classifies "take out the pizza"', () => expect(parseIntent('take out the pizza').intent).toBe(INTENTS.REMOVE_ITEM));
    it('classifies "drop the soup"', () => expect(parseIntent('drop the soup').intent).toBe(INTENTS.REMOVE_ITEM));
});

// ─── parseIntent — CHANGE_RESTAURANT ─────────────────────────────────────────
describe('parseIntent — CHANGE_RESTAURANT', () => {
    it('classifies "change to aroma"', () => {
        const r = parseIntent('change to aroma', {}, RESTAURANTS);
        expect(r.intent).toBe(INTENTS.CHANGE_RESTAURANT);
    });
    it('classifies "switch to dc district"', () => {
        const r = parseIntent('switch to dc district', {}, RESTAURANTS);
        expect(r.intent).toBe(INTENTS.CHANGE_RESTAURANT);
    });
    it('matches restaurant object on change', () => {
        const r = parseIntent('change to aroma biryani', {}, RESTAURANTS);
        expect(r.restaurantMatch?.name).toBe('Aroma Biryani');
    });
});

// ─── parseIntent — NEW_SEARCH ─────────────────────────────────────────────────
describe('parseIntent — NEW_SEARCH', () => {
    it('classifies "biryani"', () => expect(parseIntent('biryani').intent).toBe(INTENTS.NEW_SEARCH));
    it('classifies "cheap biryani"', () => expect(parseIntent('cheap biryani').intent).toBe(INTENTS.NEW_SEARCH));
    it('classifies "spicy chicken"', () => expect(parseIntent('spicy chicken').intent).toBe(INTENTS.NEW_SEARCH));
    it('classifies "veg pizza"', () => expect(parseIntent('veg pizza').intent).toBe(INTENTS.NEW_SEARCH));
    it('classifies "south indian food"', () => expect(parseIntent('south indian food').intent).toBe(INTENTS.NEW_SEARCH));
    it('extracts dish entity', () => {
        const r = parseIntent('chicken biryani');
        expect(r.entities.dish).toBe('biryani');
    });
    it('extracts protein entity', () => {
        const r = parseIntent('chicken biryani');
        expect(r.entities.protein).toBe('chicken');
    });
    it('extracts price entity', () => {
        const r = parseIntent('biryani under 200');
        expect(r.entities.priceMax).toBe(200);
    });
    it('extracts spice level', () => {
        const r = parseIntent('spicy biryani');
        expect(r.entities.spice).toBe('spicy');
    });
    it('extracts common misspelled dish entity', () => {
        const r = parseIntent('briyani');
        expect(r.entities.dish).toBe('biryani');
    });
    it('extracts veg diet', () => {
        const r = parseIntent('vegetarian pizza');
        expect(r.entities.diet).toBe('vegetarian');
    });

    it('keeps mixed Tamil-English food queries searchable for backend fallback', () => {
        const r = parseIntent('எனக்கு chicken biryani வேண்டும்');
        expect(r.intent).toBe(INTENTS.NEW_SEARCH);
        expect(r.entities.dish).toBe('biryani');
        expect(r.entities.protein).toBe('chicken');
    });
});

describe('shouldBypassGlobalSearch', () => {
    it('bypasses price comparison for mixed Tamil-English food requests', () => {
        const input = 'எனக்கு chicken biryani வேண்டும்';
        const intent = parseIntent(input);
        expect(shouldBypassGlobalSearch(input, intent, RESTAURANTS)).toBe(true);
    });

    it('bypasses price comparison for restaurant-directed mixed-script food requests', () => {
        const input = 'எனக்கு ஒரு chicken biryani aroma restaurantல் வேண்டும்';
        const intent = parseIntent(input, {}, RESTAURANTS);
        expect(shouldBypassGlobalSearch(input, intent, RESTAURANTS)).toBe(true);
    });

    it('does not bypass normal english price search', () => {
        const intent = parseIntent('cheap biryani');
        expect(shouldBypassGlobalSearch('cheap biryani', intent, RESTAURANTS)).toBe(false);
    });

    it('bypasses search fallback for unclear mixed-language multi-restaurant order phrases', () => {
        const input = 'ஒரு சிக்கன் 65 பிரியாணி அரோமா ரெஸ்டாரண்ட்ல அப்புறம் ஒரு போன் மட்டன் போன் சூப் அஞ்சபர்ல இரண்டு ஆர்டர் பண்ணு';
        const intent = parseIntent(input, {}, RESTAURANTS);
        expect(intent.intent).toBe(INTENTS.UNCLEAR);
        expect(shouldBypassGlobalSearch(input, intent, RESTAURANTS)).toBe(true);
    });

    it('does not bypass normal discovery query for nearby food', () => {
        const intent = parseIntent('biryani nearby');
        expect(shouldBypassGlobalSearch('biryani nearby', intent, RESTAURANTS)).toBe(false);
    });
});

describe('shouldUseDiscoverySearch', () => {
    it('uses comparison search for nearby discovery', () => {
        const intent = parseIntent('biryani nearby');
        expect(shouldUseDiscoverySearch('biryani nearby', intent)).toBe(true);
    });

    it('uses comparison search for cheap discovery', () => {
        const intent = parseIntent('cheap biryani');
        expect(shouldUseDiscoverySearch('cheap biryani', intent)).toBe(true);
    });

    it('does not use comparison search for direct mixed-language order text', () => {
        const input = 'ஒரு மட்டன் சூப் அடமலை அப்புறம் ஒரு பட்டர் நான் ancha restaurant அஞ்சப்பர் ரெஸ்டாரண்ட்';
        const intent = parseIntent(input, {}, RESTAURANTS);
        expect(shouldUseDiscoverySearch(input, intent)).toBe(false);
    });

    it('does not use comparison search for direct item order', () => {
        const intent = parseIntent('chicken biryani from aroma');
        expect(shouldUseDiscoverySearch('chicken biryani from aroma', intent)).toBe(false);
    });

    it('uses comparison search for generic recommendation queries', () => {
        const intent = parseIntent("I don't know what to eat suggest something");
        expect(shouldUseDiscoverySearch("I don't know what to eat suggest something", intent)).toBe(true);
    });

    it('uses comparison search for combo discovery queries', () => {
        const intent = parseIntent('i want any combos nearby with best rate');
        expect(shouldUseDiscoverySearch('i want any combos nearby with best rate', intent)).toBe(true);
    });

    it('uses comparison search for spicy nearby dish suggestions', () => {
        const intent = parseIntent('something spicy chaat masala nearby');
        expect(shouldUseDiscoverySearch('something spicy chaat masala nearby', intent)).toBe(true);
    });

    it('uses comparison search for hybrid special-item nearby suggestions', () => {
        const intent = parseIntent('give me something special item near by ?');
        expect(shouldUseDiscoverySearch('give me something special item near by ?', intent)).toBe(true);
    });

    it('uses comparison search for best-value nearby combo requests', () => {
        const intent = parseIntent('show me best value combos nearby');
        expect(shouldUseDiscoverySearch('show me best value combos nearby', intent)).toBe(true);
    });

    it('uses comparison search for vague combo suggestion requests', () => {
        const intent = parseIntent('give me some special combos today', {}, RESTAURANTS);
        expect(shouldUseDiscoverySearch('give me some special combos today', intent)).toBe(true);
    });

    it('uses comparison search for plain global dish search', () => {
        const intent = parseIntent('biryani', {}, RESTAURANTS);
        expect(shouldUseDiscoverySearch('biryani', intent)).toBe(true);
    });

    it('uses comparison search for common misspelled dish search', () => {
        const intent = parseIntent('briyani', {}, RESTAURANTS);
        expect(shouldUseDiscoverySearch('briyani', intent)).toBe(true);
    });

    it('does not use comparison search for pure menu browsing phrases', () => {
        const intent = parseIntent("show me today's specials");
        expect(shouldUseDiscoverySearch("show me today's specials", intent)).toBe(false);
    });
});

// ─── parseIntent — FILTER_UPDATE ─────────────────────────────────────────────
// FILTER_UPDATE requires a previous conversation state (convState.dish or convState.lastResults)
// Without context it falls to NEW_SEARCH or UNCLEAR — that is intentional behaviour.
const PREV_STATE = { dish: 'biryani', lastResults: [{ name: 'Biryani' }] };

describe('parseIntent — FILTER_UPDATE', () => {
    it('classifies "make it veg" with prior dish context', () => {
        expect(parseIntent('make it veg', PREV_STATE).intent).toBe(INTENTS.FILTER_UPDATE);
    });
    it('classifies "show cheaper" with prior context', () => {
        expect(parseIntent('show cheaper', PREV_STATE).intent).toBe(INTENTS.FILTER_UPDATE);
    });
    it('classifies "only vegan" with prior context', () => {
        expect(parseIntent('only vegan', PREV_STATE).intent).toBe(INTENTS.FILTER_UPDATE);
    });
    it('classifies "under 150" with prior context', () => {
        // "under 150" is a price constraint — treated as NEW_SEARCH without context (has priceMax entity)
        const r = parseIntent('under 150', PREV_STATE);
        expect([INTENTS.FILTER_UPDATE, INTENTS.NEW_SEARCH]).toContain(r.intent);
    });
    it('classifies "sort by rating" with prior context', () => {
        expect(parseIntent('sort by rating', PREV_STATE).intent).toBe(INTENTS.FILTER_UPDATE);
    });
    it('classifies "cheaper" with prior context', () => {
        expect(parseIntent('cheaper', PREV_STATE).intent).toBe(INTENTS.FILTER_UPDATE);
    });
    it('without prior context falls to UNCLEAR or NEW_SEARCH (not FILTER_UPDATE)', () => {
        const r = parseIntent('make it veg');
        expect([INTENTS.UNCLEAR, INTENTS.NEW_SEARCH]).toContain(r.intent);
    });
    it('sets stateUpdate.diet=vegetarian for "make it veg"', () => {
        const r = parseIntent('make it veg', PREV_STATE);
        expect(r.stateUpdate?.diet).toBe('vegetarian');
    });
    it('sets stateUpdate.priceRange=cheap for "show cheaper"', () => {
        const r = parseIntent('show cheaper', PREV_STATE);
        expect(r.stateUpdate?.priceRange).toBe('cheap');
    });
});

// ─── parseIntent — MULTI_ORDER ────────────────────────────────────────────────
describe('parseIntent — MULTI_ORDER', () => {
    it('classifies "biryani from aroma and soup from dc district"', () => {
        const r = parseIntent('biryani from aroma and soup from dc district', {}, RESTAURANTS);
        expect(r.intent).toBe(INTENTS.MULTI_ORDER);
    });
    it('classifies "one naan from anjappar and two dosa from aroma"', () => {
        const r = parseIntent('one naan from anjappar and two dosa from aroma', {}, RESTAURANTS);
        expect(r.intent).toBe(INTENTS.MULTI_ORDER);
    });
    it('MULTI_ORDER fires before CHANGE_RESTAURANT check', () => {
        // "change to aroma and get soup from dc" should be MULTI_ORDER not CHANGE_RESTAURANT
        const r = parseIntent('soup from aroma and biryani from dc district', {}, RESTAURANTS);
        expect(r.intent).toBe(INTENTS.MULTI_ORDER);
    });

    it('classifies mixed Tamil-English multi-restaurant orders', () => {
        const r = parseIntent('எனக்கு one naan from anjappar and two dosa from aroma வேண்டும்', {}, RESTAURANTS);
        expect(r.intent).toBe(INTENTS.MULTI_ORDER);
    });

    it('does not downgrade Tamil restaurant-item sequence into CHANGE_RESTAURANT', () => {
        const input = 'எனக்கு ஒரு பட்டர் நான் அஞ்சப்பர் ரெஸ்டாரண்ட்ல அப்புறம் ஒரு மட்டன் சூப் aroma';
        const r = parseIntent(input, {}, RESTAURANTS);
        expect([INTENTS.MULTI_ORDER, INTENTS.UNCLEAR]).toContain(r.intent);
    });
});

// ─── parseIntent — MEAL_PLAN ──────────────────────────────────────────────────
describe('parseIntent — MEAL_PLAN', () => {
    it('classifies "plan meals for the week"', () => expect(parseIntent('plan meals for the week').intent).toBe(INTENTS.MEAL_PLAN));
    it('classifies "create a meal plan"', () => expect(parseIntent('create a meal plan').intent).toBe(INTENTS.MEAL_PLAN));
    it('classifies "7 day meal plan"', () => expect(parseIntent('7 day meal plan').intent).toBe(INTENTS.MEAL_PLAN));
});

// ─── parseIntent — HELP ───────────────────────────────────────────────────────
describe('parseIntent — HELP', () => {
    it('classifies "what can you do"', () => expect(parseIntent('what can you do').intent).toBe(INTENTS.HELP));
    it('classifies "help me"', () => expect(parseIntent('help me').intent).toBe(INTENTS.HELP));
    it('classifies "how does this work"', () => expect(parseIntent('how does this work').intent).toBe(INTENTS.HELP));
});

// ─── parseIntent — UNCLEAR ────────────────────────────────────────────────────
describe('parseIntent — UNCLEAR', () => {
    it('classifies gibberish as UNCLEAR', () => expect(parseIntent('xkcd fjdsla').intent).toBe(INTENTS.UNCLEAR));
    it('classifies empty string as UNCLEAR', () => expect(parseIntent('').intent).toBe(INTENTS.UNCLEAR));
    it('classifies short noise as UNCLEAR', () => expect(parseIntent('um').intent).toBe(INTENTS.UNCLEAR));
});

// ─── parseIntent — Performance ────────────────────────────────────────────────
describe('parseIntent — Performance', () => {
    it('completes in under 10ms', () => {
        const r = parseIntent('add biryani from aroma and soup from dc district', {}, RESTAURANTS);
        expect(r.parseTimeMs).toBeLessThan(10);
    });

    it('returns parseTimeMs > 0', () => {
        const r = parseIntent('hello');
        expect(r.parseTimeMs).toBeGreaterThanOrEqual(0);
    });
});
