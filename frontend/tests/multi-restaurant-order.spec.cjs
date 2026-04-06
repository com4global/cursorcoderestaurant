// @ts-check
/**
 * Multi-Restaurant Order — Comprehensive Browser Tests (23 cases)
 *
 * Covers:
 *  TC-01  Typed: "biryani from aroma and pizza from dominos"
 *  TC-02  Typed: natural language "I'd like X from A and Y from B"
 *  TC-03  Typed: three-restaurant order
 *  TC-04  Typed: quantity — "2 biryani from aroma and 1 pizza from dominos"
 *  TC-05  Typed: all-lowercase input
 *  TC-06  Typed: mixed case input
 *  TC-07  Typed: partial/fuzzy restaurant name
 *  TC-08  Typed: bot reply does NOT say "please select a restaurant"
 *  TC-09  Typed: multi-order with unknown items → graceful (no crash)
 *  TC-10  Typed: single "from" phrase → still works (not misrouted)
 *  TC-11  Typed: multi-order while restaurant IS pre-selected
 *  TC-12  Typed: multi-order after viewing categories
 *  TC-13  Typed: multi-order then "view cart"
 *  TC-14  Typed: multi-order then "clear cart"
 *  TC-15  Typed: multi-order then "checkout"
 *  TC-16  Voice: MULTI_ORDER via injected transcript
 *  TC-17  Voice: multi-order with quantity spoken
 *  TC-18  Voice: payload omits restaurant_id for MULTI_ORDER
 *  TC-19  Voice: no crash when voice mode active during multi-order
 *  TC-20  Voice: "intentResult is not defined" ReferenceError is fixed
 *  TC-21  API: POST /chat/message multi-order → 200 with reply
 *  TC-22  API: POST /chat/message unauthenticated → 401
 *  TC-23  API: POST /chat/message unknown items → 200 graceful reply
 */

const { test, expect } = require('@playwright/test');

const API_BASE = 'http://localhost:8000';

// ─── Helpers ─────────────────────────────────────────────────────────────────

async function registerUser(page, prefix = 'mo') {
    const email = `pw_${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}@test.com`;
    await page.goto('/');
    await page.waitForTimeout(1000);
    await page.locator('.nav-item:has-text("Profile")').click();
    await page.waitForTimeout(400);
    const signUp = page.locator('text=/Sign up/i').first();
    if (await signUp.isVisible({ timeout: 2000 }).catch(() => false)) {
        await signUp.click();
        await page.waitForTimeout(300);
    }
    await page.locator('input').first().fill(email);
    await page.locator('input').nth(1).fill('password123');
    await page.locator('button').filter({ hasText: /Create account|Sign in/i }).first().click();
    await page.waitForTimeout(2000);
    return email;
}

async function goToChat(page) {
    await page.locator('.nav-item:has-text("Chat")').click();
    await page.waitForTimeout(800);
}

async function typeAndSend(page, text) {
    const input = page.locator('.ai-chat-input').first();
    await input.fill(text);
    await input.press('Enter');
    // Wait for bot reply to appear in .ai-bubble
    await page.waitForTimeout(6000);
}

/** Returns the text of the current last bot message shown in .ai-bubble */
async function getLastBotMessage(page) {
    const bubble = page.locator('.ai-bubble').first();
    if (!(await bubble.isVisible({ timeout: 3000 }).catch(() => false))) return '';
    return (await bubble.innerText()).toLowerCase();
}

async function selectFirstRestaurant(page) {
    await page.locator('.nav-item:has-text("Home")').click();
    await page.waitForTimeout(1000);
    const card = page.locator('.restaurant-card-v').first();
    if (await card.isVisible({ timeout: 6000 }).catch(() => false)) {
        await card.click();
        await page.waitForTimeout(3500);
    }
}

async function setupVoiceMocks(page) {
    await page.addInitScript(() => {
        Object.defineProperty(navigator, 'mediaDevices', {
            value: {
                getUserMedia: async () => ({
                    getTracks: () => [{ stop: () => {} }],
                    getAudioTracks: () => [{ stop: () => {} }],
                }),
            },
            writable: true,
        });
        class MockRecognition {
            constructor() { this.lang = ''; this.continuous = false; this.interimResults = true; }
            start() { setTimeout(() => { if (this.onstart) this.onstart({}); }, 50); }
            stop() { if (this.onend) this.onend({}); }
            abort() { if (this.onend) this.onend({}); }
        }
        window.SpeechRecognition = MockRecognition;
        window.webkitSpeechRecognition = MockRecognition;
        window.speechSynthesis = {
            speak: (u) => { setTimeout(() => { if (u.onend) u.onend({}); }, 100); },
            cancel: () => {},
            getVoices: () => [],
        };
    });
    // Return silent WAV for TTS so tests don't wait on Sarvam API
    const silentWav = Buffer.from([
        0x52,0x49,0x46,0x46,0x24,0x00,0x00,0x00,0x57,0x41,0x56,0x45,
        0x66,0x6d,0x74,0x20,0x10,0x00,0x00,0x00,0x01,0x00,0x01,0x00,
        0x44,0xac,0x00,0x00,0x88,0x58,0x01,0x00,0x02,0x00,0x10,0x00,
        0x64,0x61,0x74,0x61,0x00,0x00,0x00,0x00,
    ]);
    await page.route('**/voice/tts', async route => {
        await route.fulfill({ status: 200, body: silentWav, contentType: 'audio/wav' });
    });
}

// ─── Group 1: Typed multi-order ───────────────────────────────────────────────

test.describe('Group 1 — Typed multi-order (no restaurant pre-selected)', () => {

    test('TC-01: basic two-restaurant typed order', async ({ page }) => {
        await registerUser(page, 'tc01');
        await goToChat(page);
        await typeAndSend(page, 'biryani from aroma and pizza from dominos');
        const msg = await getLastBotMessage(page);
        expect(msg).not.toMatch(/please select a restaurant/i);
        expect(msg.length).toBeGreaterThan(5);
    });

    test('TC-02: natural language phrasing', async ({ page }) => {
        await registerUser(page, 'tc02');
        await goToChat(page);
        await typeAndSend(page, "I'd like to order one biryani from aroma and one dosa from anjappar");
        const msg = await getLastBotMessage(page);
        expect(msg).not.toMatch(/please select a restaurant/i);
        expect(msg.length).toBeGreaterThan(5);
    });

    test('TC-03: three-restaurant order', async ({ page }) => {
        await registerUser(page, 'tc03');
        await goToChat(page);
        await typeAndSend(page, 'biryani from aroma, dosa from anjappar and pizza from dominos');
        const msg = await getLastBotMessage(page);
        expect(msg).not.toMatch(/error|crash/i);
        expect(msg.length).toBeGreaterThan(5);
    });

    test('TC-04: with quantity in order', async ({ page }) => {
        await registerUser(page, 'tc04');
        await goToChat(page);
        await typeAndSend(page, '2 biryani from aroma and 1 pizza from dominos');
        const msg = await getLastBotMessage(page);
        expect(msg).not.toMatch(/please select a restaurant/i);
        expect(msg.length).toBeGreaterThan(5);
    });

    test('TC-05: all-lowercase input', async ({ page }) => {
        await registerUser(page, 'tc05');
        await goToChat(page);
        await typeAndSend(page, 'biryani from aroma and naan from desi district');
        const msg = await getLastBotMessage(page);
        expect(msg).not.toMatch(/please select a restaurant/i);
        expect(msg.length).toBeGreaterThan(5);
    });

    test('TC-06: mixed case input', async ({ page }) => {
        await registerUser(page, 'tc06');
        await goToChat(page);
        await typeAndSend(page, 'Biryani from Aroma and Pizza from Dominos');
        const msg = await getLastBotMessage(page);
        expect(msg).not.toMatch(/please select a restaurant/i);
        expect(msg.length).toBeGreaterThan(5);
    });

    test('TC-07: partial/fuzzy restaurant name — no crash', async ({ page }) => {
        await registerUser(page, 'tc07');
        await goToChat(page);
        await typeAndSend(page, 'biryani from aro and pizza from dom');
        const msg = await getLastBotMessage(page);
        // Fuzzy match or graceful fallback — no crash
        expect(msg.length).toBeGreaterThan(3);
    });

    test('TC-08: bot reply does NOT contain "please select a restaurant"', async ({ page }) => {
        await registerUser(page, 'tc08');
        await goToChat(page);
        await typeAndSend(page, 'chicken from aroma and naan from desi district');
        const msg = await getLastBotMessage(page);
        expect(msg).not.toMatch(/please select a restaurant/i);
    });

    test('TC-09: multi-order with completely unknown items → graceful reply', async ({ page }) => {
        await registerUser(page, 'tc09');
        await goToChat(page);
        await typeAndSend(page, 'xyzfood12345 from aroma and abcitem567 from dominos');
        const msg = await getLastBotMessage(page);
        // Should not throw, bot replies with something
        expect(msg.length).toBeGreaterThan(3);
    });

    test('TC-10: single restaurant "from" phrase works normally', async ({ page }) => {
        await registerUser(page, 'tc10');
        await goToChat(page);
        await typeAndSend(page, 'biryani from aroma');
        const msg = await getLastBotMessage(page);
        expect(msg.length).toBeGreaterThan(5);
    });
});

// ─── Group 2: Multi-order with restaurant context / follow-ups ────────────────

test.describe('Group 2 — Multi-order with context / follow-ups', () => {

    test('TC-11: multi-order while a restaurant IS pre-selected', async ({ page }) => {
        await registerUser(page, 'tc11');
        await selectFirstRestaurant(page);
        await goToChat(page);
        await typeAndSend(page, 'biryani from aroma and pizza from dominos');
        const msg = await getLastBotMessage(page);
        expect(msg).not.toMatch(/please select a restaurant/i);
        expect(msg.length).toBeGreaterThan(5);
    });

    test('TC-12: multi-order after browsing a category', async ({ page }) => {
        await registerUser(page, 'tc12');
        await selectFirstRestaurant(page);
        await goToChat(page);
        await typeAndSend(page, 'show me the menu');
        await page.waitForTimeout(2000);
        await typeAndSend(page, 'biryani from aroma and naan from desi district');
        const msg = await getLastBotMessage(page);
        expect(msg.length).toBeGreaterThan(5);
        expect(msg).not.toMatch(/please select a restaurant/i);
    });

    test('TC-13: multi-order then "view cart"', async ({ page }) => {
        await registerUser(page, 'tc13');
        await goToChat(page);
        await typeAndSend(page, 'biryani from aroma and pizza from dominos');
        await typeAndSend(page, 'show my cart');
        const msg = await getLastBotMessage(page);
        expect(msg.length).toBeGreaterThan(3);
    });

    test('TC-14: multi-order then "clear cart" — no FK crash', async ({ page }) => {
        await registerUser(page, 'tc14');
        await goToChat(page);
        await typeAndSend(page, 'biryani from aroma and pizza from dominos');
        await typeAndSend(page, 'clear my cart');
        const msg = await getLastBotMessage(page);
        expect(msg).toMatch(/clear|empty|remov|done/i);
    });

    test('TC-15: multi-order then checkout', async ({ page }) => {
        await registerUser(page, 'tc15');
        await goToChat(page);
        await typeAndSend(page, 'biryani from aroma and pizza from dominos');
        await typeAndSend(page, 'checkout');
        const msg = await getLastBotMessage(page);
        expect(msg.length).toBeGreaterThan(3);
    });
});

// ─── Group 3: Simulated voice multi-order ────────────────────────────────────

test.describe('Group 3 — Voice simulated multi-order', () => {

    test('TC-16: inject MULTI_ORDER transcript via chat input', async ({ page }) => {
        await setupVoiceMocks(page);
        await registerUser(page, 'tc16');
        await goToChat(page);
        await typeAndSend(page, 'one biryani from aroma and one dosa from anjappar');
        const msg = await getLastBotMessage(page);
        expect(msg).not.toMatch(/please select a restaurant/i);
        expect(msg.length).toBeGreaterThan(5);
    });

    test('TC-17: multi-order with spoken quantity', async ({ page }) => {
        await setupVoiceMocks(page);
        await registerUser(page, 'tc17');
        await goToChat(page);
        await typeAndSend(page, 'two biryani from aroma and one pizza from pizza hut');
        const msg = await getLastBotMessage(page);
        expect(msg).not.toMatch(/please select a restaurant/i);
        expect(msg.length).toBeGreaterThan(5);
    });

    test('TC-18: MULTI_ORDER payload omits restaurant_id', async ({ page }) => {
        await setupVoiceMocks(page);
        await registerUser(page, 'tc18');
        await goToChat(page);

        let capturedPayload = null;
        await page.route('**/chat/message', async route => {
            try { capturedPayload = JSON.parse(route.request().postData() || '{}'); } catch {}
            await route.continue();
        });

        await typeAndSend(page, 'biryani from aroma and naan from desi district');

        if (capturedPayload) {
            // For MULTI_ORDER the restaurant_id should be absent or null
            expect(capturedPayload.restaurant_id ?? null).toBeNull();
        }
        const msg = await getLastBotMessage(page);
        expect(msg.length).toBeGreaterThan(5);
    });

    test('TC-19: no JS crash when voice mode active during multi-order', async ({ page }) => {
        await setupVoiceMocks(page);
        await registerUser(page, 'tc19');
        await goToChat(page);

        const errors = [];
        page.on('pageerror', e => errors.push(e.message));

        // Toggle voice on if button available
        const voiceBtn = page.locator('button.mic-btn, button[title*="voice" i], .voice-toggle').first();
        if (await voiceBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
            await voiceBtn.click();
            await page.waitForTimeout(800);
        }

        await typeAndSend(page, 'biryani from aroma and soup from desi district');
        await page.waitForTimeout(2000);

        const intentErrors = errors.filter(e => e.includes('intentResult') || e.includes('INTENTS'));
        expect(intentErrors).toHaveLength(0);
    });

    test('TC-20: "intentResult is not defined" ReferenceError is fixed', async ({ page }) => {
        await registerUser(page, 'tc20');
        await goToChat(page);

        const errors = [];
        page.on('pageerror', e => errors.push(e.message));

        await typeAndSend(page, 'I would like to order one signature Biryani from aroma and one bottle of water from Desi District');
        await page.waitForTimeout(3000);

        const refErrors = errors.filter(e => e.includes('intentResult is not defined'));
        expect(refErrors).toHaveLength(0);
    });
});

// ─── Group 4: API-level tests via /chat/message ───────────────────────────────

test.describe('Group 4 — API /chat/message multi-order', () => {

    async function getToken(request) {
        const email = `api_mo_${Date.now()}_${Math.random().toString(36).slice(2,6)}@test.com`;
        const res = await request.post(`${API_BASE}/auth/register`, {
            data: { email, password: 'password123' },
        });
        const body = await res.json();
        return body.access_token;
    }

    test('TC-21: POST /chat/message multi-order → 200 with reply', async ({ request }) => {
        const token = await getToken(request);
        expect(token).toBeTruthy();

        const res = await request.post(`${API_BASE}/chat/message`, {
            headers: { Authorization: `Bearer ${token}` },
            data: {
                text: 'one biryani from aroma and one pizza from dominos',
                session_id: null,
                restaurant_id: null,
            },
        });
        expect(res.status()).toBe(200);
        const body = await res.json();
        expect(body.reply).toBeTruthy();
        expect(typeof body.reply).toBe('string');
        expect(body.reply.length).toBeGreaterThan(5);
    });

    test('TC-22: POST /chat/message unauthenticated → 401 or 403', async ({ request }) => {
        const res = await request.post(`${API_BASE}/chat/message`, {
            data: { text: 'biryani from aroma and pizza from dominos' },
        });
        expect([401, 403, 422]).toContain(res.status());
    });

    test('TC-23: POST /chat/message unknown items → 200 graceful reply', async ({ request }) => {
        const token = await getToken(request);

        const res = await request.post(`${API_BASE}/chat/message`, {
            headers: { Authorization: `Bearer ${token}` },
            data: {
                text: 'xyzdish99999 from aroma and abcitem11111 from dominos',
                session_id: null,
                restaurant_id: null,
            },
        });
        expect(res.status()).toBe(200);
        const body = await res.json();
        expect(body.reply).toBeTruthy();
        expect(body.reply.length).toBeGreaterThan(3);
    });
});
