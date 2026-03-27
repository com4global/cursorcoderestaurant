// @ts-check
const { test, expect } = require('@playwright/test');

async function injectAICallReturnMocks(page, { paymentStatus = 'success', cartState, myOrders } = {}) {
    const resolvedCartState = cartState || { restaurants: [], grand_total_cents: 0 };
    const resolvedOrders = myOrders || [];

    await page.addInitScript(({ paymentStatus }) => {
        localStorage.setItem('token', 'pw-ai-call-token');
        localStorage.setItem('aiCallCheckoutContext', JSON.stringify({ sessionId: 'call-session-1' }));

        const originalPlay = window.Audio && window.Audio.prototype ? window.Audio.prototype.play : null;
        if (originalPlay) {
            window.Audio.prototype.play = function play() {
                setTimeout(() => {
                    if (typeof this.onended === 'function') this.onended(new Event('ended'));
                }, 20);
                return Promise.resolve();
            };
        }

        Object.defineProperty(navigator, 'mediaDevices', {
            value: {
                getUserMedia: async () => ({
                    getTracks: () => [{ stop: () => {} }],
                }),
            },
            configurable: true,
        });

        window.__AI_CALL_PAYMENT_STATUS__ = paymentStatus;
    }, { paymentStatus });

    await page.route('**/restaurants**', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    });
    await page.route('**/nearby**', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    });
    await page.route('**/cart', async (route) => {
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(resolvedCartState),
        });
    });
    await page.route('**/my-orders', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(resolvedOrders) });
    });
    await page.route('**/checkout/verify', async (route) => {
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ ok: true, status: 'paid', orders: [] }),
        });
    });
    await page.route('**/api/call-order/session/call-session-1', async (route) => {
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
                session_id: 'call-session-1',
                language: 'en-IN',
                state: 'ready',
                assistant_reply: 'Moved 1 item from your draft order into your cart across 1 restaurant.',
                history: [
                    { role: 'assistant', text: 'Hello. I am your AI food ordering assistant. What would you like to eat today?' },
                ],
                selected_restaurant: null,
                selected_item: null,
                draft_cart: [],
                pending_action: null,
                draft_total_items: 0,
                draft_total_cents: 0,
            }),
        });
    });
    await page.route('**/api/voice/tts', async (route) => {
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ audio_base64: null, format: 'wav' }),
        });
    });
}

test.describe('AI Call Checkout Return', () => {
    test('restores AI Call transcript with a completion message after payment success', async ({ page }) => {
        await injectAICallReturnMocks(page, { paymentStatus: 'success' });

        await page.goto('/?payment=order_success&session_id=stripe-session-1');

        await expect(page.locator('.ai-call-title')).toContainText('Talk to RestaurantAI like a live call', { timeout: 10000 });
        await expect(page.locator('.ai-call-bubble-assistant').last()).toContainText(
            'Your payment is complete and the order is confirmed',
            { timeout: 10000 }
        );
    });

    test('updates shared order state after AI Call payment success', async ({ page }) => {
        await injectAICallReturnMocks(page, {
            paymentStatus: 'success',
            myOrders: [
                {
                    id: 401,
                    restaurant_name: 'A2B',
                    created_at: new Date().toISOString(),
                    total_cents: 899,
                    status: 'confirmed',
                    queue_position: 1,
                    estimated_ready_at: new Date(Date.now() + 20 * 60 * 1000).toISOString(),
                    items: [
                        { name: 'Veg Kurma', quantity: 1 },
                    ],
                },
            ],
        });

        await page.goto('/?payment=order_success&session_id=stripe-session-1');

        await expect(page.locator('.ai-call-bubble-assistant').last()).toContainText(
            'Your payment is complete and the order is confirmed',
            { timeout: 10000 }
        );
        await expect(page.locator('.nav-item:has-text("Orders") .nav-badge')).toContainText('1', { timeout: 10000 });

        await page.locator('.nav-item:has-text("Orders")').click();
        await expect(page.locator('.orders-title')).toContainText('Your Orders', { timeout: 10000 });
        await expect(page.locator('.order-card').first()).toContainText('A2B');
        await expect(page.locator('.order-card').first()).toContainText('1x Veg Kurma');
        await expect(page.locator('.order-card').first()).toContainText('$8.99');
    });

    test('restores AI Call transcript with a cancellation message after payment cancel', async ({ page }) => {
        await injectAICallReturnMocks(page, { paymentStatus: 'cancel' });

        await page.goto('/?payment=order_cancel');

        await expect(page.locator('.ai-call-title')).toContainText('Talk to RestaurantAI like a live call', { timeout: 10000 });
        await expect(page.locator('.ai-call-bubble-assistant').last()).toContainText(
            'The payment was cancelled',
            { timeout: 10000 }
        );
    });

    test('keeps shared cart items visible after AI Call checkout cancellation', async ({ page }) => {
        await injectAICallReturnMocks(page, {
            paymentStatus: 'cancel',
            cartState: {
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
        });

        await page.goto('/?payment=order_cancel');

        await expect(page.locator('.ai-call-bubble-assistant').last()).toContainText(
            'The payment was cancelled',
            { timeout: 10000 }
        );

        await page.locator('.nav-item:has-text("Chat")').click();
        await expect(page.locator('.chat-cart-btn')).toBeVisible({ timeout: 10000 });
        await expect(page.locator('.chat-cart-btn')).toContainText('$8.99');

        await page.locator('.chat-cart-btn').click();
        const cartPanel = page.locator('.cart-panel').first();
        await expect(cartPanel).toBeVisible({ timeout: 10000 });
        await expect(cartPanel).toContainText('A2B');
        await expect(cartPanel).toContainText('1x Veg Kurma');
        await expect(page.locator('.cart-grand-total')).toContainText('$8.99');
    });
});