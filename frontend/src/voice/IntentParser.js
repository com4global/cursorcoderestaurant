/**
 * IntentParser.js — Ultra-fast local intent extraction + routing (<10ms)
 * 
 * Extracts BOTH:
 * 1. Structured entities (dish, protein, price, spice, cuisine, diet)
 * 2. Intent classification (NEW_SEARCH, FILTER_UPDATE, CHANGE_RESTAURANT, etc.)
 * 
 * Used with ConversationState to maintain context across turns.
 */

import { pipelineLog } from './VoicePipelineLog.jsx';

// ─── Entity databases ───────────────────────────────────────────────
const DISHES = [
    'biryani', 'pizza', 'burger', 'pasta', 'naan', 'curry', 'tikka', 'masala',
    'dosa', 'idli', 'samosa', 'pakora', 'roti', 'paratha', 'paneer', 'dal',
    'rice', 'fried rice', 'noodles', 'momos', 'tandoori', 'kebab', 'wrap',
    'sandwich', 'salad', 'soup', 'steak', 'wings', 'fries', 'tacos', 'burrito',
    'sushi', 'ramen', 'pho', 'pad thai', 'shawarma', 'falafel', 'hummus',
    'chaat', 'pani puri', 'vada pav', 'chole bhature', 'butter chicken',
    'chicken tikka', 'fish curry', 'mutton', 'lamb', 'prawn', 'shrimp',
    'ice cream', 'gulab jamun', 'jalebi', 'kheer', 'cake', 'brownie',
    'lassi', 'chai', 'coffee', 'juice', 'smoothie', 'milkshake', 'tea',
];

const PROTEINS = ['chicken', 'mutton', 'lamb', 'fish', 'prawn', 'shrimp', 'egg', 'paneer', 'tofu', 'beef', 'pork'];
const SPICE_LEVELS = ['extra spicy', 'not spicy', 'less spicy', 'spicy', 'mild', 'medium', 'hot'];
const CUISINES = ['south indian', 'north indian', 'indo-chinese', 'indian', 'chinese', 'italian', 'mexican', 'thai', 'japanese', 'american', 'mediterranean', 'korean', 'mughlai'];
const DIETS = ['vegetarian', 'vegan', 'non-veg', 'non veg', 'halal', 'gluten-free', 'keto', 'low-carb', 'jain', 'veg'];
const DISH_FUZZY_IGNORE_WORDS = new Set([
    'today', 'todays', 'todays', 'special', 'specials', 'menu', 'menus', 'item', 'items',
    'option', 'options', 'something', 'anything', 'show', 'give', 'nearby', 'cheap', 'cheapest',
    'best', 'popular', 'what', 'have', 'here', 'some', 'recommend', 'suggest', 'find', 'price',
]);

// Words that mean menu categories/sections — don't treat as restaurant name when user says e.g. "drinks"
const CATEGORY_LIKE_WORDS = new Set([
    'drinks', 'beverages', 'starters', 'mains', 'main', 'desserts', 'dessert',
    'appetizers', 'appetizer', 'sides', 'side', 'specials', 'combo', 'combos',
    'family', 'kids', 'breakfast', 'lunch', 'dinner', 'snacks', 'soups', 'salads',
]);

// ─── Intent types ───────────────────────────────────────────────────
export const INTENTS = {
    NEW_SEARCH: 'NEW_SEARCH',           // "cheap biryani" — fresh food search
    FILTER_UPDATE: 'FILTER_UPDATE',     // "make it veg", "show cheaper", "only 4 star"
    CHANGE_RESTAURANT: 'CHANGE_RESTAURANT', // "change to desi district"
    ADD_TO_CART: 'ADD_TO_CART',         // "add 2 biryani", "order that"
    REMOVE_ITEM: 'REMOVE_ITEM',        // "remove naan"
    CHECKOUT: 'CHECKOUT',              // "place order", "checkout"
    GREETING: 'GREETING',              // "hello", "hi"
    HELP: 'HELP',                      // "what can you do"
    THANKS: 'THANKS',                  // "thanks"
    GOODBYE: 'GOODBYE',               // "bye"
    MEAL_PLAN: 'MEAL_PLAN',            // "plan meals for the week"
    SHOW_CART: 'SHOW_CART',            // "what's in my cart", "show cart"
    CLEAR_CART: 'CLEAR_CART',          // "clear the cart", "order fresh"
    MULTI_ORDER: 'MULTI_ORDER',        // "biryani from aroma and soup from anjappar"
    UNCLEAR: 'UNCLEAR',                // Can't classify
};

/**
 * Detect multi-restaurant order: "X from RestA and Y from RestB"
 * Returns true if input clearly spans multiple restaurants.
 * restaurants = array of {name, slug} objects (optional, improves accuracy)
 */
export function detectMultiOrder(text, restaurants = []) {
    const t = text.toLowerCase().trim();
    // Need at least 2 "from X" or "at X" clauses.
    // Capture candidate restaurant phrases until the next connector or end of string.
    const fromMatches = [...t.matchAll(/(?:from|at)\s+([^,]+?)(?=\s+and\b|\s+also\b|\s*,|$)/gi)];
    if (fromMatches.length < 2) return false;

    // At least one of the "from X" must resolve to a known restaurant
    if (restaurants.length === 0) return true; // no list to check against — optimistically true

    const allNames = restaurants.flatMap(r => [
        r.name.toLowerCase(),
        r.slug.replace(/-/g, ' '),
        ...r.name.toLowerCase().split(/\s+/),
    ]);
    return fromMatches.some((fm) => {
        const candidate = (fm[1] || '').replace(/\s+and.*$/i, '').trim();
        return allNames.some(n => n.includes(candidate) || candidate.includes(n.split(' ')[0]));
    });
}

export function shouldBypassGlobalSearch(text, intentResult = {}, restaurants = []) {
    const t = String(text || '').toLowerCase().trim();
    if (!t) return false;

    const entities = intentResult.entities || {};
    const hasFoodEntity = Boolean(entities.dish || entities.protein || entities.cuisine || entities.priceMax);
    const hasNonLatinScript = /[^\u0000-\u00ff]/u.test(t);
    const hasRestaurantMarker = /\b(from|at|in|restaurant|hotel|menu)\b/i.test(t) || /ரெஸ்டார|ஹோட்டல்|மெனு/u.test(t);
    const hasDiscoveryHint = /\b(nearby|near me|cheap|cheapest|compare|comparison|best value|lowest|price|options|suggest|find me|show me)\b/i.test(t);
    if (hasDiscoveryHint) return false;

    const hasQuantity = /(?<!\S)(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|ஒரு|இரண்டு|மூன்று)\b/i.test(t);
    const hasOrderVerb = /\b(order|add|get|i want|i need|give me|have)\b/i.test(t) || /ஆர்டர்|வேண்டும்|பண்ணு|கொடுங்க|எனக்கு/u.test(t);
    const hasTamilConnector = /அப்புறம்|பிறகு|மற்றும்|அடுத்து/u.test(t);
    const hasRestaurantName = restaurants.some((restaurant) => {
        const name = String(restaurant?.name || '').toLowerCase();
        const slug = String(restaurant?.slug || '').replace(/-/g, ' ').toLowerCase();
        return (name && t.includes(name)) || (slug && t.includes(slug));
    });

    if (intentResult.intent === INTENTS.MULTI_ORDER) return true;

    return (
        (hasFoodEntity || hasOrderVerb || hasQuantity)
        && (hasNonLatinScript || hasRestaurantMarker || hasTamilConnector || hasRestaurantName)
    );
}

export function shouldUseDiscoverySearch(text, intentResult = {}) {
    const t = String(text || '').toLowerCase().trim();
    if (!t) return false;

    const entities = intentResult.entities || {};
    const hasDishEntity = Boolean(entities.dish || entities.protein || entities.cuisine);
    const hasDirectOrderCommand = /^(?:add|order|get\s+me|give\s+me|get|i(?:'ll|\s+will)\s+(?:have|take|get)|i\s+want|i\s+need|i'?d\s+like)\b/i.test(t);
    const isMenuBrowseRequest = /today'?s\s+specials?|\bspecials?\b|\bmenu\b|\bmenus\b|\bcategories?\b|\boptions?\b|\bwhat\s+do\s+you\s+have\b|\bshow\s+me\b/i.test(t);
    const hasDiscoveryHint = /\b(nearby|near\s+by|near me|cheap|cheapest|compare|comparison|best value|best rate|lowest|price|options|suggest|recommend|recommend me|find me|show me|restaurants with|where can i get|where can i find|who has|which restaurant has|popular|combo|combos|meal deal|deals?)\b/i.test(t);
    const hasFoodSignal = Boolean(entities.dish || entities.protein || entities.cuisine || entities.priceMax || /\b(biryani|pizza|burger|soup|dosa|naan|curry|rice|coffee|tea|chicken|mutton|chaat|masala|combo|combos|meal|meals)\b/i.test(t));
    const hasRecommendationQuery = /don'?t\s+know\s+what\s+to\s+eat|what\s+should\s+i\s+eat|what\s+to\s+eat|suggest\s+something|recommend\s+something|surprise\s+me|dinner\s+ideas|lunch\s+ideas|any\s+combos?|something\s+(?:cheap|spicy|tasty|good|special)|special\s+item|popular\s+dishes?/i.test(t);
    return (hasDiscoveryHint && (hasFoodSignal || hasRecommendationQuery)) || (hasDishEntity && !hasDirectOrderCommand && !isMenuBrowseRequest && !/\bfrom\b/i.test(t));
}

function shouldTreatAsDiscoveryStyleRequest(text, entities = {}) {
    return shouldUseDiscoverySearch(text, { entities });
}

function countRestaurantMentions(text, restaurants = []) {
    const t = String(text || '').toLowerCase();
    if (!t || restaurants.length === 0) return 0;

    const matchedIds = new Set();
    restaurants.forEach((restaurant, index) => {
        const name = String(restaurant?.name || '').toLowerCase();
        const slug = String(restaurant?.slug || '').replace(/-/g, ' ').toLowerCase();
        const shortName = name.split(/\s+/).filter(Boolean)[0] || '';

        if (
            (name && t.includes(name))
            || (slug && t.includes(slug))
            || (shortName && shortName.length >= 4 && t.includes(shortName))
        ) {
            matchedIds.add(restaurant?.id ?? `idx:${index}`);
        }
    });

    return matchedIds.size;
}

function detectOrderLikeRestaurantFlow(text, restaurants = []) {
    const t = String(text || '').toLowerCase().trim();
    if (!t) {
        return {
            restaurantMentions: 0,
            hasFoodSignal: false,
            hasQuantity: false,
            hasOrderVerb: false,
            hasConnector: false,
            looksLikeOrder: false,
            looksLikeMultiRestaurantOrder: false,
        };
    }

    const restaurantMentions = countRestaurantMentions(t, restaurants);
    const hasFoodSignal = Boolean(
        extractDish(t)
        || PROTEINS.some((protein) => t.includes(protein))
        || /சூப்|பிரியாணி|நான்|தோசை|குழம்பு|சிக்கன்|மட்டன்|பட்டர்/u.test(t)
    );
    const hasQuantity = /(?<!\S)(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|ஒரு|இரண்டு|மூன்று|நாலு|அஞ்சு)\b/i.test(t);
    const hasOrderVerb = /\b(order|add|get|i want|i need|give me|have)\b/i.test(t) || /ஆர்டர்|வேண்டும்|பண்ணு|கொடுங்க|எனக்கு/u.test(t);
    const hasConnector = /\b(and|then|after|next)\b/i.test(t) || /அப்புறம்|பிறகு|மற்றும்|அடுத்து/u.test(t);
    const looksLikeOrder = hasFoodSignal && (hasQuantity || hasOrderVerb || hasConnector);

    return {
        restaurantMentions,
        hasFoodSignal,
        hasQuantity,
        hasOrderVerb,
        hasConnector,
        looksLikeOrder,
        looksLikeMultiRestaurantOrder: looksLikeOrder && restaurantMentions >= 2,
    };
}

// ─── Intent detection patterns ──────────────────────────────────────

const CHANGE_RESTAURANT_PATTERNS = [
    /^(?:change|switch|move|go)\s+(?:to|the\s+restaurant\s+to)\s+/i,
    /^(?:order|get|eat)\s+(?:from|at)\s+/i,
    /^(?:show|open|select|pick|choose|try|use|browse)\s+/i,
    /(?:from|at|in)\s+(.+?)(?:\s+restaurant|\s+menu)?\s*$/i,
];

const FILTER_UPDATE_PATTERNS = [
    /^(?:make\s+it|only|show|filter|just|change\s+to)\s+(veg|vegetarian|vegan|non-?veg|halal|gluten.?free|spicy|mild|cheap|cheaper|expensive)/i,
    /^(?:show|get|find)\s+(?:me\s+)?(?:only\s+)?(cheaper|spicier|milder|better|higher.?rated|closest|nearest)/i,
    /^(?:under|below|less\s+than|max|budget)\s+\$?\d+/i,
    /^(?:only|at\s+least|minimum)\s+(\d+)\s*(?:star|rating)/i,
    /^(?:sort|order)\s+by\s+(price|rating|distance|popular)/i,
    /^(cheaper|spicier|milder|closer|better|higher.?rated|lowest.?price|highest.?rated)/i,
];

const ADD_TO_CART_PATTERNS = [
    /^(?:add|order|get|i(?:'ll|\s+will)\s+(?:have|take|get)|give\s+me|get\s+me|i\s+want|i\s+need|i'?d\s+like)\b/i,
    /^(?:add)\s+(?:to\s+cart|that|this|it)/i,
    /^(?:order)\s+(?:that|this|it|the)/i,
];

const MENU_BROWSE_PATTERNS = [
    /today'?s\s+specials?/i,
    /\bspecials?\b/i,
    /\bmenu\b|\bmenus\b/i,
    /\bcategories?\b/i,
    /\boptions?\b/i,
    /\bwhat\s+do\s+you\s+have\b/i,
    /\bshow\s+me\b/i,
];

const REMOVE_PATTERNS = [
    /^(?:remove|delete|cancel|take\s+out|drop)\s+/i,
];

const CHECKOUT_PATTERNS = [
    /^(?:checkout|check\s+out|place\s+(?:my\s+)?order|submit|confirm|pay|finish|done|complete)\s*$/i,
    /^(?:i'?m\s+done|that'?s\s+(?:all|it)|nothing\s+else)\s*$/i,
];

const SHOW_CART_PATTERNS = [
    /^(?:show\s+(?:me\s+)?(?:my\s+)?(?:the\s+)?cart|what'?s?\s+(?:in\s+)?(?:my\s+)?cart|view\s+cart|my\s+cart|my\s+order|cart)\s*$/i,
];

const CLEAR_CART_PATTERNS = [
    /^(?:clear|empty)\s+(?:the\s+)?(?:my\s+)?cart\s*$/i,
    /^(?:clear|empty)\s+(?:the\s+)?(?:my\s+)?order\s*$/i,
    /^order\s+fresh\s*$/i,
    /^start\s+fresh\s*$/i,
    /^(?:cancel|clear)\s+(?:my\s+)?order\s*$/i,
    /^remove\s+all\s*$/i,
    /^clear\s+all\s*$/i,
    /^(?:i\s+want\s+to\s+|please\s+)?clear\s+(?:the\s+)?(?:my\s+)?cart/i,
    // Voice often transcribes "cart" as "court" or "car"
    /^clear\s+(?:the\s+)?(?:court|car)(?:\s+completely)?\s*$/i,
    /^clear\s+my\s+(?:court|car)(?:\s+completely)?\s*$/i,
];

const GREETING_PATTERNS = [
    /^(?:hi|hello|hey|howdy|yo|sup|good\s+(?:morning|afternoon|evening|night)|can\s+you\s+hear\s+me|test(?:ing)?|mic\s+(?:test|check))[\s?!.]*$/i,
];

const HELP_PATTERNS = [
    /^(?:what\s+can\s+you\s+do|how\s+(?:do(?:es)?)\s+(?:this|it)\s+work|help(?:\s+me)?|what\s+(?:is|are)\s+(?:this|you))[\s?!]*$/i,
];

const THANKS_PATTERNS = [
    /^(?:thank(?:s|\s+you)|thanks\s+a\s+lot|appreciate\s+it|thx|ty)[\s?!.]*$/i,
];

const GOODBYE_PATTERNS = [
    /^(?:bye|goodbye|see\s+you|later|good\s+night|gotta\s+go|exit|quit|stop|end)[\s?!.]*$/i,
];

const MEAL_PLAN_PATTERNS = [
    /(?:plan|create|make|generate|build)\s+(?:my\s+|a\s+)?(?:meal|food|dinner|lunch)s?\s*(?:plan)?/i,
    /meal\s*plan/i,
    /(?:weekly|daily|\d+\s*day)\s+(?:meal|food)\s*plan/i,
];

/**
 * Parse user utterance and classify intent (<10ms)
 * @param {string} text - Raw user text
 * @param {object} convState - Current conversation state
 * @param {Array} restaurants - Available restaurants for matching
 * @returns {{ intent, entities, restaurantMatch, raw, parseTimeMs }}
 */
export function parseIntent(text, convState = {}, restaurants = []) {
    const result = _parseIntentInner(text, convState, restaurants);
    pipelineLog('INTENT', `Parsed: ${result.intent}`, {
        intent: result.intent,
        raw: text.substring(0, 80),
        entities: Object.keys(result.entities).length > 0 ? result.entities : null,
        restaurantMatch: result.restaurantMatch?.name || null,
        parseTimeMs: +result.parseTimeMs.toFixed(1),
    });
    return result;
}

function _parseIntentInner(text, convState = {}, restaurants = []) {
    const t = text.toLowerCase().trim();
    const start = performance.now();
    const orderLikeRestaurantFlow = detectOrderLikeRestaurantFlow(t, restaurants);
    const shouldBlockRestaurantSwitch = orderLikeRestaurantFlow.looksLikeOrder
        && (orderLikeRestaurantFlow.restaurantMentions >= 1 || /ரெஸ்டார|ஹோட்டல்|மெனு/u.test(t));

    const result = {
        intent: INTENTS.UNCLEAR,
        entities: {},    // Extracted entities (dish, protein, price, etc.)
        stateUpdate: {}, // Fields to update in conversation state
        restaurantMatch: null, // Matched restaurant object
        raw: text,
        parseTimeMs: 0,
    };

    // ─── 0. Multi-restaurant order (fast exit — must check before CHANGE_RESTAURANT) ─
    if (detectMultiOrder(t, restaurants)) {
        result.intent = INTENTS.MULTI_ORDER;
        result.parseTimeMs = performance.now() - start;
        return result;
    }

    if (orderLikeRestaurantFlow.looksLikeMultiRestaurantOrder) {
        result.intent = INTENTS.MULTI_ORDER;
        result.parseTimeMs = performance.now() - start;
        return result;
    }

    // ─── 1. Greeting/Help/Thanks/Goodbye (fast exit) ─────────────
    if (GREETING_PATTERNS.some(p => p.test(t))) {
        result.intent = INTENTS.GREETING;
        result.parseTimeMs = performance.now() - start;
        return result;
    }
    if (HELP_PATTERNS.some(p => p.test(t))) {
        result.intent = INTENTS.HELP;
        result.parseTimeMs = performance.now() - start;
        return result;
    }
    if (THANKS_PATTERNS.some(p => p.test(t))) {
        result.intent = INTENTS.THANKS;
        result.parseTimeMs = performance.now() - start;
        return result;
    }
    if (GOODBYE_PATTERNS.some(p => p.test(t))) {
        result.intent = INTENTS.GOODBYE;
        result.parseTimeMs = performance.now() - start;
        return result;
    }

    // ─── 2. Checkout ─────────────────────────────────────────────
    if (CHECKOUT_PATTERNS.some(p => p.test(t))) {
        result.intent = INTENTS.CHECKOUT;
        result.parseTimeMs = performance.now() - start;
        return result;
    }

    // ─── 3. Show cart ────────────────────────────────────────────
    if (SHOW_CART_PATTERNS.some(p => p.test(t))) {
        result.intent = INTENTS.SHOW_CART;
        result.parseTimeMs = performance.now() - start;
        return result;
    }

    // ─── 3b. Clear cart / order fresh ─────────────────────────────
    if (CLEAR_CART_PATTERNS.some(p => p.test(t))) {
        result.intent = INTENTS.CLEAR_CART;
        result.parseTimeMs = performance.now() - start;
        return result;
    }

    // ─── 4. Meal plan ────────────────────────────────────────────
    if (MEAL_PLAN_PATTERNS.some(p => p.test(t))) {
        result.intent = INTENTS.MEAL_PLAN;
        result.parseTimeMs = performance.now() - start;
        return result;
    }

    // ─── 5. Remove item ──────────────────────────────────────────
    if (REMOVE_PATTERNS.some(p => p.test(t))) {
        result.intent = INTENTS.REMOVE_ITEM;
        result.parseTimeMs = performance.now() - start;
        return result;
    }

    // ─── 5b. Change restaurant (no target) — "change restaurant", "switch restaurant", "different restaurant", etc.
    // Backend will show restaurant list; no restaurantMatch so we send raw text to chat
    const wantDifferentRestaurantPhrases = [
        /^(?:change|switch)\s+(?:the\s+)?restaurant\s*$/i,
        /^(?:different|another|other|new)\s+restaurant\s*$/i,
        /^go\s+back\s*$/i,
        /^back\s+to\s+restaurants\s*$/i,
        /^(?:show|list|see)\s+restaurants\s*$/i,
        /^which\s+restaurants\s*$/i,
        /(?:want|like)\s+to\s+(?:change|switch)\s+(?:the\s+)?restaurant/i,
        /(?:pick|choose|select)\s+another\s+restaurant/i,
        /(?:go\s+back|see\s+other)\s+to\s+restaurants/i,
    ];
    if (wantDifferentRestaurantPhrases.some(p => p.test(t))) {
        result.intent = INTENTS.CHANGE_RESTAURANT;
        result.restaurantMatch = null; // no specific restaurant — backend will show list
        result.parseTimeMs = performance.now() - start;
        return result;
    }

    // ─── 6. Change restaurant (to specific name) ───────────────────
    if (restaurants.length > 0) {
        // If the text looks like an order with quantities + "from", let the backend
        // handle it (multi-restaurant parsing) instead of treating it as CHANGE_RESTAURANT.
        const fromMatches = t.match(/\sfrom\s/g) || [];
        const hasQtyWord = /\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\b/.test(t);
        const looksLikeOrderFrom = (fromMatches.length >= 1 && hasQtyWord) || orderLikeRestaurantFlow.looksLikeOrder;
        if (!looksLikeOrderFrom && !shouldBlockRestaurantSwitch) {
            // "go to the restaurant DC District" → extract "DC District" (voice often says "DC" for "Desi")
            const goToRestaurantRegex = /^go\s+to\s+the\s+restaurant\s+(?:to\s+)?/i;
            const switchRegex = /^(?:change|switch|move)\s+(?:to\s+|the\s+restaurant\s+to\s+)/i;
            const switchRegexGo = /^go\s+to\s+the\s+restaurant\s+to\s+/i;
            const fromRegex = /(?:from|at|in)\s+(.+?)(?:\s+restaurant|\s+menu)?\s*$/i;
            const selectRegex = /^(?:show|open|select|pick|choose|try|use|browse|order\s+from)\s+/i;
            // Handle 'I want to select X restaurant', 'can you select the restaurant X', 'take me to X', 'let's try X'
            const wantSelectRegex = /(?:i\s+want\s+(?:to\s+)?(?:select|go\s+to|try|visit|order\s+from|eat\s+(?:at|from))\s+|take\s+me\s+to\s+|let'?s?\s+(?:go\s+to|try|eat\s+at)\s+|(?:can|could|would)\s+you\s+(?:please\s+)?(?:select|switch\s+to|change\s+to|go\s+to|open|show)\s+(?:the\s+)?(?:restaurant\s+)?|please\s+(?:select|switch\s+to|change\s+to|go\s+to|open)\s+(?:the\s+)?(?:restaurant\s+)?)(.+?)(?:\s+restaurant|\s+menu)?\s*$/i;

            let candidateName = null;

            if (goToRestaurantRegex.test(t)) {
                candidateName = t.replace(goToRestaurantRegex, '').trim();
            } else if (switchRegex.test(t)) {
                candidateName = t.replace(switchRegex, '').trim();
            } else if (switchRegexGo.test(t)) {
                candidateName = t.replace(switchRegexGo, '').trim();
            } else if (wantSelectRegex.test(t)) {
                candidateName = t.match(wantSelectRegex)?.[1]?.trim();
            } else if (fromRegex.test(t)) {
                candidateName = t.match(fromRegex)?.[1]?.trim();
            } else if (selectRegex.test(t)) {
                candidateName = t.replace(selectRegex, '').trim();
            }

            if (candidateName) {
                const match = fuzzyMatchRestaurant(candidateName, restaurants);
                if (match) {
                    result.intent = INTENTS.CHANGE_RESTAURANT;
                    result.restaurantMatch = match;
                    result.stateUpdate = { restaurant: match.name, restaurantId: match.id };
                    result.parseTimeMs = performance.now() - start;
                    return result;
                }
            }

            // Also check if the entire input IS a restaurant name (skip if it's a category word like "drinks")
            const isCategoryLike = CATEGORY_LIKE_WORDS.has(t) || (t.split(/\s+/).length === 1 && [...CATEGORY_LIKE_WORDS].some(w => w.includes(t) || t.includes(w)));
            const directMatch = isCategoryLike ? null : fuzzyMatchRestaurant(t, restaurants);
            if (directMatch && !extractDish(t)) {
                result.intent = INTENTS.CHANGE_RESTAURANT;
                result.restaurantMatch = directMatch;
                result.stateUpdate = { restaurant: directMatch.name, restaurantId: directMatch.id };
                result.parseTimeMs = performance.now() - start;
                return result;
            }
        }
    }

    // ─── 7. Extract entities ─────────────────────────────────────
    const entities = extractEntities(t);
    result.entities = entities;
    const isMenuBrowseRequest = MENU_BROWSE_PATTERNS.some((p) => p.test(t));
    const isDiscoveryStyleRequest = shouldTreatAsDiscoveryStyleRequest(t, entities);

    if (
        shouldBlockRestaurantSwitch
        && !orderLikeRestaurantFlow.looksLikeMultiRestaurantOrder
        && !entities.dish
        && !entities.protein
        && !entities.cuisine
        && !entities.priceMax
    ) {
        result.intent = INTENTS.UNCLEAR;
        result.parseTimeMs = performance.now() - start;
        return result;
    }

    // ─── 8. Filter update (modifier on existing results) ─────────
    if (convState.dish || convState.lastResults) {
        if (FILTER_UPDATE_PATTERNS.some(p => p.test(t))) {
            result.intent = INTENTS.FILTER_UPDATE;
            result.stateUpdate = {};

            // Parse what's being updated
            if (/cheap(?:er)?|low(?:er)?\s*price|budget|affordable/i.test(t)) {
                result.stateUpdate.priceRange = 'cheap';
                result.stateUpdate.sortBy = 'price';
            }
            if (/expensive|premium|high.?end|fancy/i.test(t)) {
                result.stateUpdate.priceRange = 'expensive';
            }
            if (/veg(?:etarian)?(?!.*non)/i.test(t) && !/non.?veg/i.test(t)) {
                result.stateUpdate.diet = 'vegetarian';
            }
            if (/non.?veg/i.test(t)) {
                result.stateUpdate.diet = 'non-veg';
            }
            if (/vegan/i.test(t)) {
                result.stateUpdate.diet = 'vegan';
            }
            if (/halal/i.test(t)) {
                result.stateUpdate.diet = 'halal';
            }
            if (/spic(?:y|ier)/i.test(t)) {
                result.stateUpdate.spice = 'spicy';
            }
            if (/mild(?:er)?/i.test(t)) {
                result.stateUpdate.spice = 'mild';
            }

            // Price constraint
            const priceMatch = t.match(/(?:under|below|max|budget)\s*\$?\s*(\d+)/i);
            if (priceMatch) result.stateUpdate.priceMax = parseInt(priceMatch[1], 10);

            // Rating
            const ratingMatch = t.match(/(\d+)\s*(?:star|rating)/i);
            if (ratingMatch) result.stateUpdate.rating = parseInt(ratingMatch[1], 10);

            // Sort
            const sortMatch = t.match(/sort\s+by\s+(price|rating|distance|popular)/i);
            if (sortMatch) result.stateUpdate.sortBy = sortMatch[1];

            // Merge any extracted entities
            if (entities.dish) result.stateUpdate.dish = entities.dish;
            if (entities.protein) result.stateUpdate.protein = entities.protein;
            if (entities.cuisine) result.stateUpdate.cuisine = entities.cuisine;

            result.parseTimeMs = performance.now() - start;
            return result;
        }
    }

    // ─── 9. Add to cart ──────────────────────────────────────────
    if (
        ADD_TO_CART_PATTERNS.some(p => p.test(t))
        && !isDiscoveryStyleRequest
        && !(isMenuBrowseRequest && !entities.dish && !entities.protein)
    ) {
        result.intent = INTENTS.ADD_TO_CART;
        // Extract quantity
        const qtyMatch = t.match(/(\d+)\s+/);
        if (qtyMatch) result.entities.quantity = parseInt(qtyMatch[1], 10);
        result.parseTimeMs = performance.now() - start;
        return result;
    }

    // ─── 10. New search (default for food queries) ───────────────
    if (entities.dish || entities.protein || entities.cuisine || entities.priceMax) {
        result.intent = INTENTS.NEW_SEARCH;
        result.stateUpdate = {
            dish: entities.dish,
            protein: entities.protein,
            cuisine: entities.cuisine,
            spice: entities.spice,
            diet: entities.diet,
            priceMax: entities.priceMax,
            priceRange: entities.priceMax ? (entities.priceMax <= 10 ? 'cheap' : entities.priceMax <= 20 ? 'mid' : 'expensive') : null,
        };
        result.parseTimeMs = performance.now() - start;
        return result;
    }

    // ─── 11. Unclear — let backend handle it ─────────────────────
    result.intent = INTENTS.UNCLEAR;
    result.parseTimeMs = performance.now() - start;
    return result;
}

// ─── Helper: extract entities from text ──────────────────────────────
function extractEntities(t) {
    const entities = {};

    // Price
    const priceMatch = t.match(/(?:under|below|less\s+than|max|up\s+to|within|budget)\s*\$?\s*(\d+)/i)
        || t.match(/\$?\s*(\d+)\s*(?:or\s+less|max|budget|dollars?)/i);
    if (priceMatch) entities.priceMax = parseInt(priceMatch[1], 10);

    // Detect "cheap" as a price signal
    if (/\bcheap(?:est|er)?\b|\bbudget\b|\baffordable\b|\blow\s*price/i.test(t)) {
        entities.priceRange = 'cheap';
    }

    // Protein
    for (const p of PROTEINS) {
        if (t.includes(p)) { entities.protein = p; break; }
    }

    // Spice (check longer phrases first)
    for (const s of SPICE_LEVELS) {
        if (t.includes(s)) { entities.spice = s; break; }
    }

    // Cuisine (check longer phrases first)
    for (const c of CUISINES) {
        if (t.includes(c)) { entities.cuisine = c; break; }
    }

    // Diet
    for (const d of DIETS) {
        if (t.includes(d)) { entities.diet = d; break; }
    }

    // Dish (longest match first)
    entities.dish = extractDish(t);

    // Quantity
    const qtyMatch = t.match(/(\d+)\s*(?:of|pieces?|plates?|servings?|orders?)/i);
    if (qtyMatch) entities.quantity = parseInt(qtyMatch[1], 10);

    return entities;
}

function extractDish(t) {
    const sortedDishes = [...DISHES].sort((a, b) => b.length - a.length);
    for (const d of sortedDishes) {
        if (t.includes(d)) return d;
    }

    const words = t.split(/[^a-z0-9]+/).filter(Boolean);
    let bestDish = null;
    let bestDistance = Number.POSITIVE_INFINITY;
    for (const word of words) {
        if (word.length < 4) continue;
        if (DISH_FUZZY_IGNORE_WORDS.has(word)) continue;
        for (const dish of sortedDishes) {
            if (Math.abs(word.length - dish.length) > 2) continue;
            const distance = editDistance(word, dish);
            const maxDistance = Math.max(2, Math.floor(dish.length * 0.25));
            if (distance <= maxDistance && distance < bestDistance) {
                bestDish = dish;
                bestDistance = distance;
            }
        }
    }
    if (bestDish) return bestDish;

    return null;
}

// ─── Helper: edit distance for voice mishearings (e.g. "DC" vs "Desi") ──
function editDistance(a, b) {
    if (a.length === 0) return b.length;
    if (b.length === 0) return a.length;
    const matrix = [];
    for (let i = 0; i <= b.length; i++) matrix[i] = [i];
    for (let j = 0; j <= a.length; j++) matrix[0][j] = j;
    for (let i = 1; i <= b.length; i++) {
        for (let j = 1; j <= a.length; j++) {
            if (b[i - 1] === a[j - 1]) matrix[i][j] = matrix[i - 1][j - 1];
            else matrix[i][j] = 1 + Math.min(matrix[i - 1][j - 1], matrix[i][j - 1], matrix[i - 1][j]);
        }
    }
    return matrix[b.length][a.length];
}

function wordSimilarity(iWord, rWord) {
    if (iWord === rWord) return true;
    if (rWord.includes(iWord) || iWord.includes(rWord)) return true;
    const len = Math.max(iWord.length, rWord.length);
    if (len <= 2) return iWord === rWord;
    const dist = editDistance(iWord, rWord);
    return dist <= 2 || dist <= Math.ceil(len * 0.4);
}

// ─── Helper: fuzzy match restaurant name ─────────────────────────────
function fuzzyMatchRestaurant(name, restaurants) {
    const lower = name.toLowerCase().replace(/restaurant|menu/gi, '').trim();
    if (!lower) return null;

    // Only DB-backed restaurants have menu/categories (OSM nearby has no id)
    const withMenu = restaurants.filter(
        (r) => r.id != null && r.id !== '' && Number.isFinite(Number(r.id))
    );
    const pool = withMenu.length ? withMenu : restaurants;

    let match = pool.find(
        (r) => r.name.toLowerCase() === lower || (r.slug || '').toLowerCase() === lower
    );
    if (match) return match;

    match = pool.find(
        (r) =>
            r.name.toLowerCase().includes(lower) ||
            lower.includes(r.name.toLowerCase()) ||
            (r.slug || '').toLowerCase().includes(lower)
    );
    if (match) return match;

    // Voice mishearings: "DC District" → "Desi District" (word-by-word similarity)
    const iWords = lower.split(/\s+/).filter(Boolean);
    if (iWords.length >= 1) {
        let best = null;
        let bestScore = 0;
        for (const r of pool) {
            const rName = r.name.toLowerCase();
            const rWords = rName.split(/\s+/).filter(Boolean);
            if (rWords.length !== iWords.length) continue;
            let score = 0;
            for (let i = 0; i < iWords.length; i++) {
                if (wordSimilarity(iWords[i], rWords[i])) score += 1;
                else if (editDistance(iWords[i], rWords[i]) <= 3) score += 0.5;
            }
            if (score > bestScore && score >= iWords.length * 0.5) {
                bestScore = score;
                best = r;
            }
        }
        if (best) return best;
    }
    return null;
}

/**
 * Build a search query string from intent result
 * Combines intent entities with conversation state
 */
export function buildSearchQuery(intentResult, convState = {}) {
    const merged = { ...convState, ...intentResult.stateUpdate };
    const parts = [];
    if (merged.priceRange) parts.push(merged.priceRange);
    if (merged.diet) parts.push(merged.diet);
    if (merged.spice) parts.push(merged.spice);
    if (merged.protein) parts.push(merged.protein);
    if (merged.dish) parts.push(merged.dish);
    if (merged.cuisine) parts.push(merged.cuisine);
    if (merged.priceMax) parts.push(`under $${merged.priceMax}`);
    return parts.join(' ') || intentResult.raw;
}
