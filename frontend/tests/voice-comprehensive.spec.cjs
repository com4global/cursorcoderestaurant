// @ts-check
const { test, expect } = require('@playwright/test');

async function registerAndGoToChat(page, prefix = 'voice') {
    const email = `pw_${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}@test.com`;
    await page.goto('/');
    await page.waitForTimeout(1200);
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
    await page.locator('.nav-item:has-text("Chat")').click();
    await page.waitForTimeout(1000);
}

async function selectFirstRestaurant(page) {
    await page.locator('.nav-item:has-text("Home")').click();
    await page.waitForTimeout(1000);
    const card = page.locator('.restaurant-card-v').first();
    await expect(card).toBeVisible({ timeout: 8000 });
    await card.click();
    await page.waitForTimeout(3500);
    await expect(page.locator('.chat-header-title')).not.toContainText('RestaurantAI', { timeout: 8000 });
}

async function injectDeniedMic(page) {
    await page.addInitScript(() => {
        navigator.mediaDevices.getUserMedia = async () => {
            throw new DOMException('Permission denied', 'NotAllowedError');
        };
        class MockSR { start() {} stop() {} abort() {} }
        window.SpeechRecognition = MockSR;
        window.webkitSpeechRecognition = MockSR;
    });
}

async function injectVoiceMocksWithTranscript(page, transcript, startDelay = 300) {
    await page.addInitScript(
        ({ transcript, startDelay }) => {
            navigator.mediaDevices.getUserMedia = async () => ({
                getTracks: () => [{ stop: () => {} }],
            });

            window.speechSynthesis = {
                cancel: () => {},
                speak: (u) => { setTimeout(() => { u.onend?.(new Event('end')); }, 80); },
                speaking: false,
                pending: false,
                paused: false,
                getVoices: () => [],
                addEventListener: () => {},
                removeEventListener: () => {},
            };

            class MockSR {
                constructor() {
                    this.onstart = null;
                    this.onresult = null;
                    this.onerror = null;
                    this.onend = null;
                }
                start() {
                    setTimeout(() => this.onstart?.(), 50);
                    setTimeout(() => {
                        this.onresult?.({
                            resultIndex: 0,
                            results: [{
                                isFinal: true,
                                0: { transcript, confidence: 0.95 },
                                length: 1,
                            }],
                            length: 1,
                        });
                        this.onend?.();
                    }, startDelay);
                }
                stop() { this.onend?.(); }
                abort() {}
            }
            window.SpeechRecognition = MockSR;
            window.webkitSpeechRecognition = MockSR;
        },
        { transcript, startDelay }
    );
}

async function startVoiceCapture(page) {
    const micBtn = page.locator('.mic-btn-ptt').first();
    await expect(micBtn).toBeVisible({ timeout: 5000 });
    await micBtn.click();
    return micBtn;
}

async function sendComposer(page) {
    await page.locator('.send-btn').click();
    await page.waitForTimeout(5000);
}

async function getLastBotBubbleText(page, timeout = 12000) {
    const bubble = page.locator('.ai-bubble').last();
    await expect(bubble).toBeVisible({ timeout });
    return (await bubble.textContent()) || '';
}

test.describe('Voice UI', () => {
    test('tap-to-dictate mic is visible in global chat', async ({ page }) => {
        await injectVoiceMocksWithTranscript(page, 'hello');
        await registerAndGoToChat(page, 'ui1');
        await expect(page.locator('.mic-btn-ptt')).toBeVisible({ timeout: 5000 });
        await expect(page.locator('.voice-lang-btn').first()).toBeVisible({ timeout: 5000 });
    });

    test('starting recording shows active state and status bar', async ({ page }) => {
        await injectVoiceMocksWithTranscript(page, 'hello', 1200);
        await registerAndGoToChat(page, 'ui2');
        const micBtn = await startVoiceCapture(page);
        await expect(micBtn).toHaveClass(/voice-active/, { timeout: 3000 });
        await expect(micBtn).toContainText('■');
        await expect(page.locator('.voice-status-bar')).toBeVisible({ timeout: 3000 });
    });

    test('denied microphone keeps the mic idle', async ({ page }) => {
        await injectDeniedMic(page);
        await registerAndGoToChat(page, 'ui3');
        const micBtn = page.locator('.mic-btn-ptt').first();
        await micBtn.click();
        await page.waitForTimeout(1000);
        await expect(micBtn).not.toHaveClass(/voice-active/);
        await expect(page.locator('.voice-status-bar')).not.toBeVisible();
    });

    test('language buttons switch between English and Tamil', async ({ page }) => {
        await injectVoiceMocksWithTranscript(page, 'hello');
        await registerAndGoToChat(page, 'ui4');
        const english = page.locator('.voice-lang-btn').filter({ hasText: 'English' });
        const tamil = page.locator('.voice-lang-btn').filter({ hasText: 'தமிழ்' });
        await expect(english).toBeVisible({ timeout: 5000 });
        await expect(tamil).toBeVisible({ timeout: 5000 });
        await tamil.click();
        await expect(tamil).toHaveClass(/active/);
        await english.click();
        await expect(english).toHaveClass(/active/);
    });
});

test.describe('Voice Transcript Flow', () => {
    test('voice transcript populates the composer in selected restaurant chat', async ({ page }) => {
        await injectVoiceMocksWithTranscript(page, 'show me biryani');
        await registerAndGoToChat(page, 'flow1');
        await selectFirstRestaurant(page);
        await startVoiceCapture(page);
        await expect(page.locator('.ai-chat-input')).toHaveValue(/show me biryani/i, { timeout: 6000 });
    });

    test('sending a captured voice transcript gets a bot reply', async ({ page }) => {
        await injectVoiceMocksWithTranscript(page, 'show me biryani');
        await registerAndGoToChat(page, 'flow2');
        await selectFirstRestaurant(page);
        await startVoiceCapture(page);
        await expect(page.locator('.ai-chat-input')).toHaveValue(/show me biryani/i, { timeout: 6000 });
        await sendComposer(page);
        const botMsg = await getLastBotBubbleText(page);
        expect(botMsg.length).toBeGreaterThan(0);
    });

    test('voice show-cart transcript can be sent to get a cart response', async ({ page }) => {
        await injectVoiceMocksWithTranscript(page, 'show cart');
        await registerAndGoToChat(page, 'flow3');
        await selectFirstRestaurant(page);
        await startVoiceCapture(page);
        await expect(page.locator('.ai-chat-input')).toHaveValue(/show cart/i, { timeout: 6000 });
        await sendComposer(page);
        const visible = await page.locator('.cart-panel, .chat-cart-btn, .chat-cart-preview, .ai-bubble').first().isVisible({ timeout: 6000 }).catch(() => false);
        expect(visible).toBe(true);
    });
});

test.describe('Voice Orders', () => {
    test('voice multi-restaurant transcript can be sent without a restaurant preselected', async ({ page }) => {
        await injectVoiceMocksWithTranscript(page, 'one biryani from Aroma and one soup from DC District');
        await registerAndGoToChat(page, 'order1');
        await startVoiceCapture(page);
        await expect(page.locator('.ai-chat-input')).toHaveValue(/one biryani from aroma and one soup from dc district/i, { timeout: 6000 });
        await sendComposer(page);
        const botMsg = await getLastBotBubbleText(page);
        expect(botMsg.length).toBeGreaterThan(0);
    });

    test('multi-restaurant voice send omits restaurant_id in chat payload', async ({ page }) => {
        await injectVoiceMocksWithTranscript(page, 'one biryani from Aroma and one soup from DC District');
        await registerAndGoToChat(page, 'order2');

        let capturedPayload = null;
        await page.route('**/chat/message', async (route) => {
            try {
                capturedPayload = JSON.parse(route.request().postData() || '{}');
            } catch {
                capturedPayload = null;
            }
            await route.continue();
        });

        await startVoiceCapture(page);
        await expect(page.locator('.ai-chat-input')).toHaveValue(/one biryani from aroma and one soup from dc district/i, { timeout: 6000 });
        await sendComposer(page);
        expect(capturedPayload).toBeTruthy();
        expect(capturedPayload.restaurant_id ?? null).toBeNull();
    });

    test('Tamil voice transcript can be sent and gets a reply', async ({ page }) => {
        await injectVoiceMocksWithTranscript(page, 'பிரியாணி வேண்டும்');
        await registerAndGoToChat(page, 'order3');
        await selectFirstRestaurant(page);
        await page.locator('.voice-lang-btn').filter({ hasText: 'தமிழ்' }).click();
        await startVoiceCapture(page);
        await expect(page.locator('.ai-chat-input')).toHaveValue(/பிரியாணி வேண்டும்/i, { timeout: 6000 });
        await sendComposer(page);
        const botMsg = await getLastBotBubbleText(page);
        expect(botMsg.length).toBeGreaterThan(0);
    });
});
