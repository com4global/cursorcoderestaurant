/**
 * Pure voice-matching logic used by doSend (fast path).
 * Extracted so we can test it against all restaurants/categories/items without the UI.
 *
 * Category shape: { id, name } (name may be string or object with .name)
 * Item shape: { id, name }
 */

const goToPrefixes = /^(?:go\s+to\s+(?:the\s+)?|show\s+me\s+(?:the\s+)?|show\s+me\s+some\s+|give\s+me\s+(?:some\s+)?|get\s+me\s+(?:some\s+)?|take\s+me\s+to\s+(?:the\s+)?|switch\s+to\s+(?:the\s+)?|i\s+want\s+(?:the\s+|some\s+)?|open\s+(?:the\s+)?|browse\s+(?:the\s+)?|what\s+are\s+(?:the\s+)?|let\s+me\s+see\s+(?:the\s+)?|can\s+i\s+see\s+(?:the\s+)?|the\s+)\s*/i;
const itemPrefixes = /^(?:add\s+|one\s+|two\s+|three\s+|four\s+|five\s+|please\s+|get\s+me\s+|i\s+want\s+|give\s+me\s+|i'll\s+have\s+|can\s+i\s+get\s+)\s*/gi;
const categoryNoiseWords = /\b(menu|menus|category|categories|items|item|options|option|list|please)\b/gi;

function norm(s) {
  return (s || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .replace(/\s+/g, '');
}

function normOneTo1(s) {
  return (s || '').replace(/one/g, '1');
}

function tokenizeName(s) {
  return (s || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .split(/\s+/)
    .filter((w) => w.length >= 2);
}

function buildTokenStats(items) {
  const tokenFreq = new Map();
  const itemTokens = items.map((item) => {
    const tokens = tokenizeName(item.name);
    const set = new Set(tokens);
    set.forEach((t) => {
      tokenFreq.set(t, (tokenFreq.get(t) || 0) + 1);
    });
    return set;
  });
  return { tokenFreq, itemTokens };
}

function scoreItemMatch(transcriptTokens, itemTokens, tokenFreq) {
  if (!transcriptTokens.length || !itemTokens.size) return 0;
  let score = 0;
  let hitCount = 0;
  transcriptTokens.forEach((tok) => {
    if (!itemTokens.has(tok)) return;
    hitCount += 1;
    const freq = tokenFreq.get(tok) || 1;
    const uniqueness = freq <= 1 ? 2.0 : freq <= 3 ? 1.0 : 0.5;
    score += uniqueness;
  });
  if (hitCount === 0) return 0;
  score += hitCount * 0.1;
  return score;
}

// Words that must not drive category match (e.g. "the" matching "Others")
const CATEGORY_STOP_WORDS = new Set([
  'the', 'and', 'for', 'from', 'other', 'others', 'change', 'restaurant', 'restaurants',
  'switch', 'take', 'want', 'like', 'show', 'open', 'go', 'me', 'to', 'that', 'this',
]);

/**
 * Match voice input to one of the active categories.
 * Uses same logic as App.jsx voice fast path (tryCandidates from input only, one/1 normalization).
 * @param {Array<{ id, name }>} activeCategories
 * @param {string} rawInput - e.g. "Desi Burgers", "buy one get one deals"
 * @returns {{ id, name } | null}
 */
export function matchCategory(activeCategories, rawInput) {
  if (!Array.isArray(activeCategories) || activeCategories.length === 0 || !rawInput?.trim()) return null;
  const trimmed = rawInput.trim();
  const phrase = trimmed.replace(goToPrefixes, '').replace(categoryNoiseWords, ' ').replace(/\s+/g, ' ').trim() || trimmed;
  const inputLower = norm(trimmed);
  const phraseLower = norm(phrase);
  const tryCandidates = [inputLower, phraseLower];
  trimmed.toLowerCase().split(/\s+/).forEach((word) => {
    const w = word.replace(/[^a-z0-9]/g, '');
    if (w.length >= 3 && !CATEGORY_STOP_WORDS.has(w) && !tryCandidates.includes(w)) tryCandidates.push(w);
  });
  for (const tryLower of tryCandidates) {
    if (!tryLower || tryLower.length < 2) continue;
    const tryAlt = normOneTo1(tryLower);
    const matched = activeCategories.find((cat) => {
      const nameStr = typeof cat.name === 'string' ? cat.name : (cat?.name?.name ?? cat?.name ?? '');
      const catLower = norm(String(nameStr));
      if (catLower.length < 2 || catLower === 'objectobject') return false;
      if (tryLower.includes(catLower) && tryLower.length > catLower.length + 3) return false;
      const match = (a, b) =>
        a === b ||
        a.startsWith(b) ||
        b.startsWith(a) ||
        (b.includes(a) && a.length >= 3) ||
        (a.includes(b) && a.length <= b.length + 2);
      return match(tryLower, catLower) || (tryAlt !== tryLower && match(tryAlt, catLower));
    });
    if (matched) return matched;
  }
  return null;
}

/**
 * Match voice input to one of the current menu items.
 * Uses token-based scoring with uniqueness, so phrases like
 * "egg frankie" prefer Egg Frankie over Chicken Frankie, and
 * avoids over-matching junk like "big gig frankie big frankie".
 * @param {Array<{ id, name }>} currentItems
 * @param {string} rawInput - e.g. "Masala Vada", "add masala vada"
 * @returns {{ id, name } | null}
 */
export function matchItem(currentItems, rawInput) {
  if (!Array.isArray(currentItems) || currentItems.length === 0 || !rawInput?.trim()) return null;
  const trimmed = rawInput.trim();
  const itemPhrase = trimmed.replace(itemPrefixes, '').trim() || trimmed;
  const normalized = itemPhrase.toLowerCase().replace(/\s+/g, ' ').trim();

  // Quick exact / substring match first
  const exact = currentItems.find((item) => (item.name || '').toLowerCase() === normalized);
  if (exact) return exact;

  const subs = currentItems.filter((item) => {
    const name = (item.name || '').toLowerCase();
    return name.includes(normalized) || normalized.includes(name);
  });
  if (subs.length === 1) return subs[0];

  const transcriptTokens = tokenizeName(itemPhrase);
  if (transcriptTokens.length === 0) return null;

  const { tokenFreq, itemTokens } = buildTokenStats(currentItems);
  let best = null;
  let bestScore = 0;
  let secondBestScore = 0;

  currentItems.forEach((item, idx) => {
    const score = scoreItemMatch(transcriptTokens, itemTokens[idx], tokenFreq);
    if (score > bestScore) {
      secondBestScore = bestScore;
      bestScore = score;
      best = item;
    } else if (score > secondBestScore) {
      secondBestScore = score;
    }
  });

  if (!best || bestScore <= 0) return null;
  // Require best to be clearly better than second-best to avoid random matches
  if (secondBestScore > 0 && bestScore < secondBestScore * 1.3) return null;

  return best;
}
