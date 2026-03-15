/**
 * VoiceValidator.js — Production voice processing pipeline
 * 
 * 5-layer validation between speech recognition and intent router:
 * 
 * Speech → Confidence → Clean → Meaningful → Keywords → Intent Router
 * 
 * Design principle: LIGHT TOUCH cleaning only.
 * Never remove words that could change meaning (not, no, etc.)
 * Only remove true verbal noise (um, uh) and dedup repeated words.
 */

// ─── Food & command dictionaries (Layer 3) ────────────────────────
const FOOD_KEYWORDS = [
    'biryani', 'pizza', 'burger', 'pasta', 'naan', 'curry', 'tikka', 'masala',
    'dosa', 'idli', 'samosa', 'pakora', 'roti', 'paratha', 'paneer', 'dal',
    'rice', 'noodles', 'momos', 'tandoori', 'kebab', 'wrap', 'sandwich',
    'salad', 'soup', 'steak', 'wings', 'fries', 'tacos', 'burrito', 'sushi',
    'ramen', 'pho', 'shawarma', 'falafel', 'hummus', 'chaat', 'chicken',
    'mutton', 'lamb', 'fish', 'prawn', 'shrimp', 'egg', 'tofu', 'beef',
    'ice cream', 'cake', 'brownie', 'lassi', 'chai', 'coffee', 'juice', 'tea',
    'smoothie', 'milkshake', 'dessert', 'bread', 'appetizer', 'entree',
    'drink', 'snack', 'breakfast', 'lunch', 'dinner', 'meal', 'food',
    'veg', 'vegetarian', 'vegan', 'non-veg', 'halal', 'spicy', 'mild',
    'cheap', 'expensive', 'budget', 'affordable', 'briyani', 'biriyani',
    'soups', 'appetizers', 'entrees', 'breads', 'desserts', 'drinks',
];

const COMMAND_KEYWORDS = [
    'show', 'find', 'search', 'order', 'add', 'remove', 'compare',
    'cheapest', 'best', 'popular', 'near', 'from', 'change', 'switch',
    'select', 'open', 'go', 'menu', 'cart', 'checkout', 'place',
    'plan', 'meal', 'help', 'hello', 'hi', 'hey', 'bye', 'thanks',
    'categories', 'filter', 'sort', 'under', 'below', 'want', 'need',
    'get', 'give', 'browse', 'try', 'visit', 'pick', 'choose',
];

// ─── Light-touch cleaning (only true noise) ────────────────────────
// IMPORTANT: Never remove words that change meaning (not, no, but, etc.)
const CLEANING_RULES = [
    [/\b(?:um|uh|uh huh|hmm|er|ah)\b/gi, ''],                     // verbal fillers only
    [/\b(\w+)(?:\s+\1){2,}\b/gi, '$1'],                            // 3+ repeats: "busy busy busy" → "busy" (keep 2)
    [/^(?:okay|ok|alright|right)\s+(?:so\s+)?/i, ''],              // "okay so show me" → "show me"
    [/^(?:hey|yo)\s+/i, ''],                                        // "hey show me" → "show me"
];

/** True if text contains Tamil or other Indic/non-Latin script (allow through keyword check). */
function hasNonLatinScript(text) {
    if (!text || !text.trim()) return false;
    // Tamil: U+0B80–U+0BFF; other Indic blocks often present in Tamil transcriptions
    return /[\u0B80-\u0BFF\u0900-\u097F]/.test(text);
}

/**
 * Validate and clean voice transcript through production pipeline.
 * 
 * @param {string} rawText - Raw speech transcript
 * @param {number} confidence - Speech confidence score (0-1), 0 = not available
 * @param {Array} restaurants - Available restaurants for name matching
 * @param {{ language?: string }} options - Optional: { language: 'ta' } to skip English-only keyword check
 * @returns {{ valid: boolean, text: string, reason: string, confidence: number, layers: string[] }}
 */
export function validateVoiceInput(rawText, confidence = 0, restaurants = [], options = {}) {
    const result = {
        valid: true,
        text: rawText.trim(),
        reason: null,
        confidence,
        layers: [],
    };

    // ─── Layer 1: Confidence filter ──────────────────────────────
    // Only reject if confidence is VERY poor AND we have a score
    if (confidence > 0 && confidence < 0.4) {
        result.valid = false;
        result.reason = 'low_confidence';
        result.layers.push(`❌ L1: Confidence too low (${(confidence * 100).toFixed(0)}% < 40%)`);
        return result;
    }
    result.layers.push(`✅ L1: Confidence ${confidence > 0 ? (confidence * 100).toFixed(0) + '%' : 'N/A'}`);

    // ─── Layer 5: Light text cleaning ────────────────────────────
    let cleaned = rawText.trim();
    for (const [pattern, replacement] of CLEANING_RULES) {
        cleaned = cleaned.replace(pattern, replacement);
    }
    cleaned = cleaned.replace(/\s{2,}/g, ' ').trim();

    if (cleaned !== rawText.trim()) {
        result.layers.push(`✅ L5: Cleaned "${rawText.trim()}" → "${cleaned}"`);
    } else {
        result.layers.push('✅ L5: No cleaning needed');
    }

    // ─── Layer 2: Non-empty check ────────────────────────────────
    if (cleaned.length === 0) {
        result.valid = false;
        result.reason = 'empty';
        result.layers.push('❌ L2: Empty after cleaning');
        return result;
    }
    result.layers.push(`✅ L2: ${cleaned.split(/\s+/).length} word(s)`);

    // ─── Layer 3: Keyword sanity check ───────────────────────────
    const lower = cleaned.toLowerCase();
    const hasFoodKw = FOOD_KEYWORDS.some(f => lower.includes(f));
    const hasCmdKw = COMMAND_KEYWORDS.some(c => lower.includes(c));
    const hasRestaurant = restaurants.some(r =>
        lower.includes(r.name.toLowerCase()) || lower.includes((r.slug || '').toLowerCase())
    );

    // Tamil / non-Latin: skip keyword rejection so "change restaurant to Aroma" etc. reach backend
    const isTamilOrNonLatin = options.language === 'ta' || hasNonLatinScript(cleaned);
    const wordCount = cleaned.split(/\s+/).length;

    if (!isTamilOrNonLatin) {
        // Short inputs (1-3 words) get a pass — might be category names like "Soups"
        if (!hasFoodKw && !hasCmdKw && !hasRestaurant && wordCount > 4) {
            result.valid = false;
            result.reason = 'no_keywords';
            result.layers.push(`❌ L3: No food/command/restaurant keywords in ${wordCount}-word input`);
            return result;
        }
    } else {
        result.layers.push('✅ L3: Tamil/non-Latin input — allowing through');
    }

    const matched = [];
    if (hasFoodKw) matched.push('food');
    if (hasCmdKw) matched.push('command');
    if (hasRestaurant) matched.push('restaurant');
    if (!isTamilOrNonLatin) {
        result.layers.push(matched.length > 0
            ? `✅ L3: Keywords: ${matched.join(', ')}`
            : `⚠️ L3: No keywords but short input (${wordCount} words) — allowing`
        );
    }

    // ─── Layer 4: Deferred to IntentParser ───────────────────────
    result.layers.push('✅ L4: Restaurant validation in IntentParser');

    result.text = cleaned;
    return result;
}

/**
 * Get a user-friendly rejection message based on reason
 */
export function getRejectionMessage(reason) {
    switch (reason) {
        case 'low_confidence':
            return "Sorry, I didn't catch that clearly. Could you say it again?";
        case 'empty':
            return "I didn't hear anything. Try saying a dish name like 'biryani' or 'pizza'.";
        case 'no_keywords':
            return "I'm not sure what you're looking for. Try a dish name, cuisine, or restaurant name.";
        default:
            return "Sorry, I didn't catch that. Could you repeat?";
    }
}
