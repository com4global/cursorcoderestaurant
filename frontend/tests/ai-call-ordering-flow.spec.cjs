// @ts-check
const { test, expect } = require('@playwright/test');

function buildTurnResponse({
    assistantReply,
    history,
    suggestions = [],
    selectedRestaurant = null,
    selectedItem = null,
    draftCart = [],
    pendingAction = null,
    draftTotalCents = 0,
    language = 'en-IN',
}) {
    return {
        session_id: 'call-flow-session',
        language,
        state: 'ready',
        assistant_reply: assistantReply,
        history,
        suggestions,
        selected_restaurant: selectedRestaurant,
        selected_item: selectedItem,
        draft_cart: draftCart,
        pending_action: pendingAction,
        draft_total_items: draftCart.reduce((sum, item) => sum + Number(item.quantity || 0), 0),
        draft_total_cents: draftTotalCents,
    };
}

async function injectAICallVoiceMocks(page) {
    await page.addInitScript(() => {
        localStorage.setItem('token', 'pw-ai-call-flow-token');

        Object.defineProperty(navigator, 'mediaDevices', {
            value: {
                getUserMedia: async () => ({
                    getTracks: () => [{ stop: () => {} }],
                }),
            },
            configurable: true,
        });

        class MockMediaRecorder {
            constructor(stream, options = {}) {
                this.stream = stream;
                this.mimeType = options.mimeType || 'audio/webm';
                this.state = 'inactive';
                this.ondataavailable = null;
                this.onstop = null;
            }
            start() {
                this.state = 'recording';
            }
            stop() {
                this.state = 'inactive';
                const blob = new Blob(['fake-audio'], { type: this.mimeType });
                this.ondataavailable?.({ data: blob });
                setTimeout(() => this.onstop?.(), 10);
            }
            static isTypeSupported() {
                return true;
            }
        }

        window.MediaRecorder = MockMediaRecorder;

        if (window.Audio && window.Audio.prototype) {
            window.Audio.prototype.play = function play() {
                setTimeout(() => {
                    if (typeof this.onended === 'function') this.onended(new Event('ended'));
                }, 20);
                return Promise.resolve();
            };
        }
    });
}

async function mockAICallRoutes(page) {
    let sttCount = 0;
    let cartState = { restaurants: [], grand_total_cents: 0 };

    const englishGreeting = 'Hello. I am your AI food ordering assistant. What would you like to eat today?';
    const tamilGreeting = 'வணக்கம். நான் உங்கள் உணவு ஆர்டர் உதவியாளர். என்ன சாப்பிட விரும்புகிறீர்கள்?';
    const vegKurmaItem = { id: 41, name: 'Veg Kurma', quantity: 1, price_cents: 899, restaurant_id: 9, restaurant_name: 'A2B' };
    const parottaItem = { id: 55, name: 'Parotta', quantity: 1, price_cents: 499, restaurant_id: 8, restaurant_name: 'Anjappar' };
    const pooriItem = { id: 61, name: 'Poori', quantity: 1, price_cents: 599, restaurant_id: 9, restaurant_name: 'A2B' };
    const paneerButterMasalaItem = { id: 71, name: 'Paneer Butter Masala', quantity: 1, price_cents: 1399, restaurant_id: 9, restaurant_name: 'A2B' };
    const tomatoRasamItem = { id: 81, name: 'Tomato Rasam', quantity: 1, price_cents: 699, restaurant_id: 9, restaurant_name: 'A2B' };

    const defaultFlow = {
        initialLanguage: 'en-IN',
        sttTranscripts: ['add veg korma', 'yes'],
        turns: {
            'add veg korma': buildTurnResponse({
                assistantReply: 'I heard 1 Veg Kurma from A2B. Should I add it to your draft order?',
                history: [
                    { role: 'assistant', text: englishGreeting },
                    { role: 'user', text: 'add veg korma' },
                    { role: 'assistant', text: 'I heard 1 Veg Kurma from A2B. Should I add it to your draft order?' },
                ],
                suggestions: [
                    { type: 'item', id: 41, name: 'Veg Kurma', restaurant_name: 'A2B', score: 0.95 },
                ],
                selectedRestaurant: { id: 9, name: 'A2B', type: 'restaurant' },
                selectedItem: { id: 41, name: 'Veg Kurma', restaurant_name: 'A2B' },
                pendingAction: { type: 'add_item', quantity: 1, item: vegKurmaItem },
            }),
            yes: buildTurnResponse({
                assistantReply: 'Added 1 Veg Kurma to your draft order. Your draft order has 1 Veg Kurma. Current total is $8.99.',
                history: [
                    { role: 'assistant', text: englishGreeting },
                    { role: 'user', text: 'add veg korma' },
                    { role: 'assistant', text: 'I heard 1 Veg Kurma from A2B. Should I add it to your draft order?' },
                    { role: 'user', text: 'yes' },
                    { role: 'assistant', text: 'Added 1 Veg Kurma to your draft order. Your draft order has 1 Veg Kurma. Current total is $8.99.' },
                ],
                selectedRestaurant: { id: 9, name: 'A2B', type: 'restaurant' },
                selectedItem: { id: 41, name: 'Veg Kurma', restaurant_name: 'A2B' },
                draftCart: [vegKurmaItem],
                draftTotalCents: 899,
            }),
        },
        finalizeResponse: {
            assistant_reply: 'Moved 1 item from your draft order into your cart across 1 restaurant.',
            history: [
                { role: 'assistant', text: englishGreeting },
                { role: 'user', text: 'add veg korma' },
                { role: 'assistant', text: 'I heard 1 Veg Kurma from A2B. Should I add it to your draft order?' },
                { role: 'user', text: 'yes' },
                { role: 'assistant', text: 'Added 1 Veg Kurma to your draft order. Your draft order has 1 Veg Kurma. Current total is $8.99.' },
                { role: 'assistant', text: 'Moved 1 item from your draft order into your cart across 1 restaurant.' },
            ],
            selected_restaurant: { id: 9, name: 'A2B', type: 'restaurant' },
            selected_item: { id: 41, name: 'Veg Kurma', restaurant_name: 'A2B' },
            draft_cart: [],
            pending_action: null,
            draft_total_items: 0,
            draft_total_cents: 0,
            materialized_item_count: 1,
            materialized_restaurant_count: 1,
        },
        cartStateAfterFinalize: {
            restaurants: [
                {
                    restaurant_id: 9,
                    restaurant_name: 'A2B',
                    order_id: 77,
                    subtotal_cents: 899,
                    items: [
                        { order_item_id: 701, name: 'Veg Kurma', quantity: 1, price_cents: 899, line_total_cents: 899 },
                    ],
                },
            ],
            grand_total_cents: 899,
        },
    };

    const tamilFlow = {
        initialLanguage: 'ta-IN',
        sttTranscripts: ['veechu parotta', 'yes', 'remove one parotta'],
        turns: {
            'veechu parotta': buildTurnResponse({
                assistantReply: 'I heard 1 Parotta from Anjappar. Should I add it to your draft order?',
                history: [
                    { role: 'assistant', text: tamilGreeting },
                    { role: 'user', text: 'veechu parotta' },
                    { role: 'assistant', text: 'I heard 1 Parotta from Anjappar. Should I add it to your draft order?' },
                ],
                suggestions: [
                    { type: 'item', id: 55, name: 'Parotta', restaurant_name: 'Anjappar', score: 0.91 },
                ],
                selectedRestaurant: { id: 8, name: 'Anjappar', type: 'restaurant' },
                selectedItem: { id: 55, name: 'Parotta', restaurant_name: 'Anjappar' },
                pendingAction: { type: 'add_item', quantity: 1, item: parottaItem },
                language: 'ta-IN',
            }),
            yes: buildTurnResponse({
                assistantReply: 'Added 1 Parotta to your draft order. Your draft order has 1 Parotta. Current total is $4.99.',
                history: [
                    { role: 'assistant', text: tamilGreeting },
                    { role: 'user', text: 'veechu parotta' },
                    { role: 'assistant', text: 'I heard 1 Parotta from Anjappar. Should I add it to your draft order?' },
                    { role: 'user', text: 'yes' },
                    { role: 'assistant', text: 'Added 1 Parotta to your draft order. Your draft order has 1 Parotta. Current total is $4.99.' },
                ],
                selectedRestaurant: { id: 8, name: 'Anjappar', type: 'restaurant' },
                selectedItem: { id: 55, name: 'Parotta', restaurant_name: 'Anjappar' },
                draftCart: [parottaItem],
                draftTotalCents: 499,
                language: 'ta-IN',
            }),
            'remove one parotta': buildTurnResponse({
                assistantReply: 'Removed 1 Parotta from your draft order. Your draft order is empty. Tell me the restaurant and dish you want to add.',
                history: [
                    { role: 'assistant', text: tamilGreeting },
                    { role: 'user', text: 'veechu parotta' },
                    { role: 'assistant', text: 'I heard 1 Parotta from Anjappar. Should I add it to your draft order?' },
                    { role: 'user', text: 'yes' },
                    { role: 'assistant', text: 'Added 1 Parotta to your draft order. Your draft order has 1 Parotta. Current total is $4.99.' },
                    { role: 'user', text: 'remove one parotta' },
                    { role: 'assistant', text: 'Removed 1 Parotta from your draft order. Your draft order is empty. Tell me the restaurant and dish you want to add.' },
                ],
                selectedRestaurant: { id: 8, name: 'Anjappar', type: 'restaurant' },
                selectedItem: { id: 55, name: 'Parotta', restaurant_name: 'Anjappar' },
                draftCart: [],
                draftTotalCents: 0,
                language: 'ta-IN',
            }),
        },
        finalizeResponse: null,
        cartStateAfterFinalize: null,
    };

    const multiItemFlow = {
        initialLanguage: 'en-IN',
        sttTranscripts: ['add veg korma', 'yes', 'add parotta', 'yes'],
        turns: {
            'add veg korma': buildTurnResponse({
                assistantReply: 'I heard 1 Veg Kurma from A2B. Should I add it to your draft order?',
                history: [
                    { role: 'assistant', text: englishGreeting },
                    { role: 'user', text: 'add veg korma' },
                    { role: 'assistant', text: 'I heard 1 Veg Kurma from A2B. Should I add it to your draft order?' },
                ],
                suggestions: [
                    { type: 'item', id: 41, name: 'Veg Kurma', restaurant_name: 'A2B', score: 0.95 },
                ],
                selectedRestaurant: { id: 9, name: 'A2B', type: 'restaurant' },
                selectedItem: { id: 41, name: 'Veg Kurma', restaurant_name: 'A2B' },
                pendingAction: { type: 'add_item', quantity: 1, item: vegKurmaItem },
            }),
            yes: buildTurnResponse({
                assistantReply: 'Added 1 Veg Kurma to your draft order. Your draft order has 1 Veg Kurma. Current total is $8.99.',
                history: [
                    { role: 'assistant', text: englishGreeting },
                    { role: 'user', text: 'add veg korma' },
                    { role: 'assistant', text: 'I heard 1 Veg Kurma from A2B. Should I add it to your draft order?' },
                    { role: 'user', text: 'yes' },
                    { role: 'assistant', text: 'Added 1 Veg Kurma to your draft order. Your draft order has 1 Veg Kurma. Current total is $8.99.' },
                ],
                selectedRestaurant: { id: 9, name: 'A2B', type: 'restaurant' },
                selectedItem: { id: 41, name: 'Veg Kurma', restaurant_name: 'A2B' },
                draftCart: [vegKurmaItem],
                draftTotalCents: 899,
            }),
            'add parotta': buildTurnResponse({
                assistantReply: 'I heard 1 Parotta from Anjappar. Should I add it to your draft order?',
                history: [
                    { role: 'assistant', text: englishGreeting },
                    { role: 'user', text: 'add veg korma' },
                    { role: 'assistant', text: 'I heard 1 Veg Kurma from A2B. Should I add it to your draft order?' },
                    { role: 'user', text: 'yes' },
                    { role: 'assistant', text: 'Added 1 Veg Kurma to your draft order. Your draft order has 1 Veg Kurma. Current total is $8.99.' },
                    { role: 'user', text: 'add parotta' },
                    { role: 'assistant', text: 'I heard 1 Parotta from Anjappar. Should I add it to your draft order?' },
                ],
                suggestions: [
                    { type: 'item', id: 55, name: 'Parotta', restaurant_name: 'Anjappar', score: 0.91 },
                ],
                selectedRestaurant: { id: 8, name: 'Anjappar', type: 'restaurant' },
                selectedItem: { id: 55, name: 'Parotta', restaurant_name: 'Anjappar' },
                draftCart: [vegKurmaItem],
                draftTotalCents: 899,
                pendingAction: { type: 'add_item', quantity: 1, item: parottaItem },
            }),
            yes_after_parotta: buildTurnResponse({
                assistantReply: 'Added 1 Parotta to your draft order. Your draft order has 1 Veg Kurma, 1 Parotta. Current total is $13.98.',
                history: [
                    { role: 'assistant', text: englishGreeting },
                    { role: 'user', text: 'add veg korma' },
                    { role: 'assistant', text: 'I heard 1 Veg Kurma from A2B. Should I add it to your draft order?' },
                    { role: 'user', text: 'yes' },
                    { role: 'assistant', text: 'Added 1 Veg Kurma to your draft order. Your draft order has 1 Veg Kurma. Current total is $8.99.' },
                    { role: 'user', text: 'add parotta' },
                    { role: 'assistant', text: 'I heard 1 Parotta from Anjappar. Should I add it to your draft order?' },
                    { role: 'user', text: 'yes' },
                    { role: 'assistant', text: 'Added 1 Parotta to your draft order. Your draft order has 1 Veg Kurma, 1 Parotta. Current total is $13.98.' },
                ],
                selectedRestaurant: { id: 8, name: 'Anjappar', type: 'restaurant' },
                selectedItem: { id: 55, name: 'Parotta', restaurant_name: 'Anjappar' },
                draftCart: [vegKurmaItem, parottaItem],
                draftTotalCents: 1398,
            }),
        },
        finalizeResponse: {
            assistant_reply: 'Moved 2 items from your draft order into your cart across 2 restaurants.',
            history: [
                { role: 'assistant', text: englishGreeting },
                { role: 'user', text: 'add veg korma' },
                { role: 'assistant', text: 'I heard 1 Veg Kurma from A2B. Should I add it to your draft order?' },
                { role: 'user', text: 'yes' },
                { role: 'assistant', text: 'Added 1 Veg Kurma to your draft order. Your draft order has 1 Veg Kurma. Current total is $8.99.' },
                { role: 'user', text: 'add parotta' },
                { role: 'assistant', text: 'I heard 1 Parotta from Anjappar. Should I add it to your draft order?' },
                { role: 'user', text: 'yes' },
                { role: 'assistant', text: 'Added 1 Parotta to your draft order. Your draft order has 1 Veg Kurma, 1 Parotta. Current total is $13.98.' },
                { role: 'assistant', text: 'Moved 2 items from your draft order into your cart across 2 restaurants.' },
            ],
            selected_restaurant: { id: 8, name: 'Anjappar', type: 'restaurant' },
            selected_item: { id: 55, name: 'Parotta', restaurant_name: 'Anjappar' },
            draft_cart: [],
            pending_action: null,
            draft_total_items: 0,
            draft_total_cents: 0,
            materialized_item_count: 2,
            materialized_restaurant_count: 2,
        },
        cartStateAfterFinalize: {
            restaurants: [
                {
                    restaurant_id: 9,
                    restaurant_name: 'A2B',
                    order_id: 77,
                    subtotal_cents: 899,
                    items: [
                        { order_item_id: 701, name: 'Veg Kurma', quantity: 1, price_cents: 899, line_total_cents: 899 },
                    ],
                },
                {
                    restaurant_id: 8,
                    restaurant_name: 'Anjappar',
                    order_id: 78,
                    subtotal_cents: 499,
                    items: [
                        { order_item_id: 702, name: 'Parotta', quantity: 1, price_cents: 499, line_total_cents: 499 },
                    ],
                },
            ],
            grand_total_cents: 1398,
        },
    };

    const pooriVariantFlow = {
        initialLanguage: 'en-IN',
        sttTranscripts: ['i want puri', 'yes'],
        turns: {
            'i want puri': buildTurnResponse({
                assistantReply: 'I heard 1 Poori from A2B. Should I add it to your draft order?',
                history: [
                    { role: 'assistant', text: englishGreeting },
                    { role: 'user', text: 'i want puri' },
                    { role: 'assistant', text: 'I heard 1 Poori from A2B. Should I add it to your draft order?' },
                ],
                suggestions: [
                    { type: 'item', id: 61, name: 'Poori', restaurant_name: 'A2B', score: 0.96 },
                ],
                selectedRestaurant: { id: 9, name: 'A2B', type: 'restaurant' },
                selectedItem: { id: 61, name: 'Poori', restaurant_name: 'A2B' },
                pendingAction: { type: 'add_item', quantity: 1, item: pooriItem },
            }),
            yes: buildTurnResponse({
                assistantReply: 'Added 1 Poori to your draft order. Your draft order has 1 Poori. Current total is $5.99.',
                history: [
                    { role: 'assistant', text: englishGreeting },
                    { role: 'user', text: 'i want puri' },
                    { role: 'assistant', text: 'I heard 1 Poori from A2B. Should I add it to your draft order?' },
                    { role: 'user', text: 'yes' },
                    { role: 'assistant', text: 'Added 1 Poori to your draft order. Your draft order has 1 Poori. Current total is $5.99.' },
                ],
                selectedRestaurant: { id: 9, name: 'A2B', type: 'restaurant' },
                selectedItem: { id: 61, name: 'Poori', restaurant_name: 'A2B' },
                draftCart: [pooriItem],
                draftTotalCents: 599,
            }),
        },
        finalizeResponse: null,
        cartStateAfterFinalize: null,
    };

    const paneerVariantFlow = {
        initialLanguage: 'en-IN',
        sttTranscripts: ['add panir butter masala', 'yes'],
        turns: {
            'add panir butter masala': buildTurnResponse({
                assistantReply: 'I heard 1 Paneer Butter Masala from A2B. Should I add it to your draft order?',
                history: [
                    { role: 'assistant', text: englishGreeting },
                    { role: 'user', text: 'add panir butter masala' },
                    { role: 'assistant', text: 'I heard 1 Paneer Butter Masala from A2B. Should I add it to your draft order?' },
                ],
                suggestions: [
                    { type: 'item', id: 71, name: 'Paneer Butter Masala', restaurant_name: 'A2B', score: 0.97 },
                ],
                selectedRestaurant: { id: 9, name: 'A2B', type: 'restaurant' },
                selectedItem: { id: 71, name: 'Paneer Butter Masala', restaurant_name: 'A2B' },
                pendingAction: { type: 'add_item', quantity: 1, item: paneerButterMasalaItem },
            }),
            yes: buildTurnResponse({
                assistantReply: 'Added 1 Paneer Butter Masala to your draft order. Your draft order has 1 Paneer Butter Masala. Current total is $13.99.',
                history: [
                    { role: 'assistant', text: englishGreeting },
                    { role: 'user', text: 'add panir butter masala' },
                    { role: 'assistant', text: 'I heard 1 Paneer Butter Masala from A2B. Should I add it to your draft order?' },
                    { role: 'user', text: 'yes' },
                    { role: 'assistant', text: 'Added 1 Paneer Butter Masala to your draft order. Your draft order has 1 Paneer Butter Masala. Current total is $13.99.' },
                ],
                selectedRestaurant: { id: 9, name: 'A2B', type: 'restaurant' },
                selectedItem: { id: 71, name: 'Paneer Butter Masala', restaurant_name: 'A2B' },
                draftCart: [paneerButterMasalaItem],
                draftTotalCents: 1399,
            }),
        },
        finalizeResponse: null,
        cartStateAfterFinalize: null,
    };

    const rasamVariantFlow = {
        initialLanguage: 'en-IN',
        sttTranscripts: ['add tomato raasam', 'yes'],
        turns: {
            'add tomato raasam': buildTurnResponse({
                assistantReply: 'I heard 1 Tomato Rasam from A2B. Should I add it to your draft order?',
                history: [
                    { role: 'assistant', text: englishGreeting },
                    { role: 'user', text: 'add tomato raasam' },
                    { role: 'assistant', text: 'I heard 1 Tomato Rasam from A2B. Should I add it to your draft order?' },
                ],
                suggestions: [
                    { type: 'item', id: 81, name: 'Tomato Rasam', restaurant_name: 'A2B', score: 0.96 },
                ],
                selectedRestaurant: { id: 9, name: 'A2B', type: 'restaurant' },
                selectedItem: { id: 81, name: 'Tomato Rasam', restaurant_name: 'A2B' },
                pendingAction: { type: 'add_item', quantity: 1, item: tomatoRasamItem },
            }),
            yes: buildTurnResponse({
                assistantReply: 'Added 1 Tomato Rasam to your draft order. Your draft order has 1 Tomato Rasam. Current total is $6.99.',
                history: [
                    { role: 'assistant', text: englishGreeting },
                    { role: 'user', text: 'add tomato raasam' },
                    { role: 'assistant', text: 'I heard 1 Tomato Rasam from A2B. Should I add it to your draft order?' },
                    { role: 'user', text: 'yes' },
                    { role: 'assistant', text: 'Added 1 Tomato Rasam to your draft order. Your draft order has 1 Tomato Rasam. Current total is $6.99.' },
                ],
                selectedRestaurant: { id: 9, name: 'A2B', type: 'restaurant' },
                selectedItem: { id: 81, name: 'Tomato Rasam', restaurant_name: 'A2B' },
                draftCart: [tomatoRasamItem],
                draftTotalCents: 699,
            }),
        },
        finalizeResponse: null,
        cartStateAfterFinalize: null,
    };

    const ambiguityFlow = {
        initialLanguage: 'en-IN',
        sttTranscripts: ['add dosa'],
        turns: {
            'add dosa': buildTurnResponse({
                assistantReply: 'I may have heard that as Plain Dosa, Masala Dosa. Which one did you mean?',
                history: [
                    { role: 'assistant', text: englishGreeting },
                    { role: 'user', text: 'add dosa' },
                    { role: 'assistant', text: 'I may have heard that as Plain Dosa, Masala Dosa. Which one did you mean?' },
                ],
                suggestions: [
                    { type: 'item', id: 91, name: 'Plain Dosa', restaurant_name: 'A2B', score: 0.84 },
                    { type: 'item', id: 92, name: 'Masala Dosa', restaurant_name: 'A2B', score: 0.81 },
                ],
                selectedRestaurant: { id: 9, name: 'A2B', type: 'restaurant' },
                selectedItem: { id: 91, name: 'Plain Dosa', restaurant_name: 'A2B' },
                pendingAction: null,
            }),
        },
        finalizeResponse: null,
        cartStateAfterFinalize: null,
    };

    let flow = defaultFlow;
    let yesCount = 0;

    await page.exposeFunction('__setAICallFlow', (flowName) => {
        flow = flowName === 'tamil-remove'
            ? tamilFlow
            : flowName === 'multi-item-cart'
                ? multiItemFlow
                : flowName === 'poori-variant'
                    ? pooriVariantFlow
                    : flowName === 'paneer-variant'
                        ? paneerVariantFlow
                        : flowName === 'rasam-variant'
                            ? rasamVariantFlow
                            : flowName === 'ambiguity-clarification'
                                ? ambiguityFlow
                    : defaultFlow;
        sttCount = 0;
        yesCount = 0;
        cartState = { restaurants: [], grand_total_cents: 0 };
    });

    await page.route('**/restaurants**', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    });
    await page.route('**/nearby**', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    });
    await page.route('**/my-orders', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    });
    await page.route('**/cart', async (route) => {
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(cartState),
        });
    });
    await page.route('**/api/voice/tts', async (route) => {
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ audio_base64: null, format: 'wav' }),
        });
    });
    await page.route('**/api/voice/stt', async (route) => {
        const transcript = flow.sttTranscripts[Math.min(sttCount, flow.sttTranscripts.length - 1)];
        sttCount += 1;
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ transcript, language: 'en-IN' }),
        });
    });
    await page.route('**/api/call-order/session', async (route) => {
        if (route.request().method() === 'POST') {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({
                    session_id: 'call-flow-session',
                    language: flow.initialLanguage,
                    state: 'ready',
                    assistant_reply: flow.initialLanguage === 'ta-IN' ? tamilGreeting : englishGreeting,
                    history: [{ role: 'assistant', text: flow.initialLanguage === 'ta-IN' ? tamilGreeting : englishGreeting }],
                    selected_restaurant: null,
                    selected_item: null,
                    draft_cart: [],
                    pending_action: null,
                    draft_total_items: 0,
                    draft_total_cents: 0,
                }),
            });
            return;
        }
        await route.continue();
    });
    await page.route('**/api/call-order/turn', async (route) => {
        const request = JSON.parse(route.request().postData() || '{}');
        let response;
        if (request.transcript === 'yes' && flow === multiItemFlow) {
            response = yesCount === 0 ? flow.turns.yes : flow.turns.yes_after_parotta;
            yesCount += 1;
        } else if (request.transcript === 'yes') {
            response = flow.turns.yes;
        } else {
            response = flow.turns[request.transcript];
        }
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(response),
        });
    });
    await page.route('**/api/call-order/session/call-flow-session/finalize', async (route) => {
        cartState = flow.cartStateAfterFinalize || cartState;
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
                session_id: 'call-flow-session',
                language: flow.initialLanguage,
                state: 'ready',
                ...flow.finalizeResponse,
            }),
        });
    });
}

test.describe('AI Call Ordering Flow', () => {
    test('handles confirm-to-draft and move-to-cart flow', async ({ page }) => {
        await injectAICallVoiceMocks(page);
        await mockAICallRoutes(page);

        await page.goto('/');
        await page.locator('.nav-item:has-text("Call")').click();

        await page.locator('button:has-text("Start AI Call")').click();
        await expect(page.locator('.ai-call-bubble-assistant').first()).toContainText('AI food ordering assistant', { timeout: 10000 });

        await page.locator('button:has-text("Speak")').click();
        await page.locator('button:has-text("Stop")').click();
        await expect(page.locator('.ai-call-pending-note')).toContainText('Waiting for confirmation: 1 x Veg Kurma', { timeout: 10000 });

        await page.locator('button:has-text("Speak")').click();
        await page.locator('button:has-text("Stop")').click();
        await expect(page.locator('.ai-call-draft-name')).toContainText('1 x Veg Kurma', { timeout: 10000 });
        await expect(page.locator('.ai-call-draft-total')).toContainText('$8.99');

        await page.getByRole('button', { name: 'Move To Cart', exact: true }).click();
        await expect(page.locator('.ai-call-status-copy')).toContainText('Draft moved into your cart', { timeout: 10000 });
        await expect(page.locator('.ai-call-note-text').filter({ hasText: 'No items added yet.' })).toBeVisible({ timeout: 10000 });
    });

    test('supports Tamil mode and remove-item flow inside AI Call', async ({ page }) => {
        await injectAICallVoiceMocks(page);
        await mockAICallRoutes(page);

        await page.goto('/');
        await page.evaluate(() => window.__setAICallFlow('tamil-remove'));
        await page.locator('.nav-item:has-text("Call")').click();
        await page.locator('.ai-call-language-btn:has-text("Tamil")').click();

        await page.locator('button:has-text("Start AI Call")').click();
        await expect(page.locator('.ai-call-bubble-assistant').first()).toContainText('உணவு ஆர்டர்', { timeout: 10000 });

        await page.locator('button:has-text("Speak")').click();
        await page.locator('button:has-text("Stop")').click();
        await expect(page.locator('.ai-call-pending-note')).toContainText('Waiting for confirmation: 1 x Parotta', { timeout: 10000 });

        await page.locator('button:has-text("Speak")').click();
        await page.locator('button:has-text("Stop")').click();
        await expect(page.locator('.ai-call-draft-name')).toContainText('1 x Parotta', { timeout: 10000 });

        await page.locator('button:has-text("Speak")').click();
        await page.locator('button:has-text("Stop")').click();
        await expect(page.locator('.ai-call-bubble-assistant').last()).toContainText('Removed 1 Parotta', { timeout: 10000 });
        await expect(page.locator('.ai-call-note-text').filter({ hasText: 'No items added yet.' })).toBeVisible({ timeout: 10000 });
    });

    test('keeps multi-item AI Call draft continuity when materializing into the shared cart UI', async ({ page }) => {
        await injectAICallVoiceMocks(page);
        await mockAICallRoutes(page);

        await page.goto('/');
        await page.evaluate(() => window.__setAICallFlow('multi-item-cart'));
        await page.locator('.nav-item:has-text("Call")').click();

        await page.locator('button:has-text("Start AI Call")').click();
        await expect(page.locator('.ai-call-bubble-assistant').first()).toContainText('AI food ordering assistant', { timeout: 10000 });

        await page.locator('button:has-text("Speak")').click();
        await page.locator('button:has-text("Stop")').click();
        await expect(page.locator('.ai-call-pending-note')).toContainText('Waiting for confirmation: 1 x Veg Kurma', { timeout: 10000 });

        await page.locator('button:has-text("Speak")').click();
        await page.locator('button:has-text("Stop")').click();
        await expect(page.locator('.ai-call-draft-name').first()).toContainText('1 x Veg Kurma', { timeout: 10000 });
        await expect(page.locator('.ai-call-draft-total')).toContainText('$8.99');

        await page.locator('button:has-text("Speak")').click();
        await page.locator('button:has-text("Stop")').click();
        await expect(page.locator('.ai-call-pending-note')).toContainText('Waiting for confirmation: 1 x Parotta', { timeout: 10000 });

        await page.locator('button:has-text("Speak")').click();
        await page.locator('button:has-text("Stop")').click();
        await expect(page.locator('.ai-call-draft-name')).toHaveCount(2, { timeout: 10000 });
        await expect(page.locator('.ai-call-draft-name').nth(0)).toContainText('1 x Veg Kurma');
        await expect(page.locator('.ai-call-draft-name').nth(1)).toContainText('1 x Parotta');
        await expect(page.locator('.ai-call-draft-total')).toContainText('$13.98');

        await page.getByRole('button', { name: 'Move To Cart', exact: true }).click();
        await expect(page.locator('.ai-call-status-copy')).toContainText('Draft moved into your cart', { timeout: 10000 });

        await page.locator('.nav-item:has-text("Chat")').click();
        await expect(page.locator('.chat-cart-btn')).toBeVisible({ timeout: 10000 });
        await expect(page.locator('.chat-cart-btn')).toContainText('$13.98');
        await page.locator('.chat-cart-btn').click();

        const cartPanel = page.locator('.cart-panel').first();
        await expect(cartPanel).toBeVisible({ timeout: 10000 });
        await expect(cartPanel).toContainText('A2B');
        await expect(cartPanel).toContainText('1x Veg Kurma');
        await expect(cartPanel).toContainText('Anjappar');
        await expect(cartPanel).toContainText('1x Parotta');
        await expect(page.locator('.cart-grand-total')).toContainText('$13.98');
    });

    test('handles pronunciation variants end to end inside AI Call', async ({ page }) => {
        await injectAICallVoiceMocks(page);
        await mockAICallRoutes(page);

        await page.goto('/');
        await page.evaluate(() => window.__setAICallFlow('poori-variant'));
        await page.locator('.nav-item:has-text("Call")').click();

        await page.locator('button:has-text("Start AI Call")').click();
        await expect(page.locator('.ai-call-bubble-assistant').first()).toContainText('AI food ordering assistant', { timeout: 10000 });

        await page.locator('button:has-text("Speak")').click();
        await page.locator('button:has-text("Stop")').click();
        await expect(page.locator('.ai-call-live-transcript')).toContainText('i want puri', { timeout: 10000 });
        await expect(page.locator('.ai-call-pending-note')).toContainText('Waiting for confirmation: 1 x Poori', { timeout: 10000 });

        await page.locator('button:has-text("Speak")').click();
        await page.locator('button:has-text("Stop")').click();
        await expect(page.locator('.ai-call-draft-name')).toContainText('1 x Poori', { timeout: 10000 });
        await expect(page.locator('.ai-call-draft-total')).toContainText('$5.99');
    });

    test('handles paneer pronunciation variants end to end inside AI Call', async ({ page }) => {
        await injectAICallVoiceMocks(page);
        await mockAICallRoutes(page);

        await page.goto('/');
        await page.evaluate(() => window.__setAICallFlow('paneer-variant'));
        await page.locator('.nav-item:has-text("Call")').click();

        await page.locator('button:has-text("Start AI Call")').click();
        await expect(page.locator('.ai-call-bubble-assistant').first()).toContainText('AI food ordering assistant', { timeout: 10000 });

        await page.locator('button:has-text("Speak")').click();
        await page.locator('button:has-text("Stop")').click();
        await expect(page.locator('.ai-call-live-transcript')).toContainText('add panir butter masala', { timeout: 10000 });
        await expect(page.locator('.ai-call-pending-note')).toContainText('Waiting for confirmation: 1 x Paneer Butter Masala', { timeout: 10000 });

        await page.locator('button:has-text("Speak")').click();
        await page.locator('button:has-text("Stop")').click();
        await expect(page.locator('.ai-call-draft-name')).toContainText('1 x Paneer Butter Masala', { timeout: 10000 });
        await expect(page.locator('.ai-call-draft-total')).toContainText('$13.99');
    });

    test('handles rasam pronunciation variants end to end inside AI Call', async ({ page }) => {
        await injectAICallVoiceMocks(page);
        await mockAICallRoutes(page);

        await page.goto('/');
        await page.evaluate(() => window.__setAICallFlow('rasam-variant'));
        await page.locator('.nav-item:has-text("Call")').click();

        await page.locator('button:has-text("Start AI Call")').click();
        await expect(page.locator('.ai-call-bubble-assistant').first()).toContainText('AI food ordering assistant', { timeout: 10000 });

        await page.locator('button:has-text("Speak")').click();
        await page.locator('button:has-text("Stop")').click();
        await expect(page.locator('.ai-call-live-transcript')).toContainText('add tomato raasam', { timeout: 10000 });
        await expect(page.locator('.ai-call-pending-note')).toContainText('Waiting for confirmation: 1 x Tomato Rasam', { timeout: 10000 });

        await page.locator('button:has-text("Speak")').click();
        await page.locator('button:has-text("Stop")').click();
        await expect(page.locator('.ai-call-draft-name')).toContainText('1 x Tomato Rasam', { timeout: 10000 });
        await expect(page.locator('.ai-call-draft-total')).toContainText('$6.99');
    });

    test('asks for clarification instead of guessing when two dishes are close matches', async ({ page }) => {
        await injectAICallVoiceMocks(page);
        await mockAICallRoutes(page);

        await page.goto('/');
        await page.evaluate(() => window.__setAICallFlow('ambiguity-clarification'));
        await page.locator('.nav-item:has-text("Call")').click();

        await page.locator('button:has-text("Start AI Call")').click();
        await expect(page.locator('.ai-call-bubble-assistant').first()).toContainText('AI food ordering assistant', { timeout: 10000 });

        await page.locator('button:has-text("Speak")').click();
        await page.locator('button:has-text("Stop")').click();
        await expect(page.locator('.ai-call-live-transcript')).toContainText('add dosa', { timeout: 10000 });
        await expect(page.locator('.ai-call-bubble-assistant').last()).toContainText('Which one did you mean?', { timeout: 10000 });
        await expect(page.locator('.ai-call-suggestion-name')).toContainText(['Plain Dosa', 'Masala Dosa']);
        await expect(page.locator('.ai-call-pending-note')).toHaveCount(0);
        await expect(page.locator('.ai-call-note-text').filter({ hasText: 'No items added yet.' })).toBeVisible({ timeout: 10000 });
    });
});