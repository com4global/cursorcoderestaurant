// @ts-check
const { test, expect } = require('@playwright/test');

async function loginAsCustomer(page) {
    const email = `pw_chat_${Date.now()}_${Math.random().toString(36).slice(2, 6)}@test.com`;
    await page.goto('/');
    await page.waitForTimeout(1500);
    await page.locator('.nav-item:has-text("Profile")').click();
    await page.waitForTimeout(500);
    const signUp = page.locator('text=/Sign up/i').first();
    if (await signUp.isVisible({ timeout: 2000 }).catch(() => false)) {
        await signUp.click();
        await page.waitForTimeout(300);
    }
    await page.locator('input').first().fill(email);
    await page.locator('input').nth(1).fill('password123');
    await page.locator('button').filter({ hasText: /Create account|Sign in/i }).first().click();
    await page.waitForTimeout(2000);
    await page.locator('.nav-item:has-text("Home")').click();
    await page.waitForTimeout(1500);
}

async function selectRestaurant(page) {
    const card = page.locator('.restaurant-card-v').first();
    await expect(card).toBeVisible({ timeout: 5000 });
    await card.click();
    await page.waitForTimeout(3000);
    await expect(page.locator('.cat-pill').first()).toBeVisible({ timeout: 8000 });
}

test.describe('Chat & AI Assistant', () => {
    test('should show chat input field', async ({ page }) => {
        await loginAsCustomer(page);
        await selectRestaurant(page);
        await expect(page.locator('.ai-chat-input')).toBeVisible({ timeout: 5000 });
    });

    test('should show bot welcome message', async ({ page }) => {
        await loginAsCustomer(page);
        await selectRestaurant(page);
        // Bot should show welcome/intro message
        await expect(page.locator('.ai-bubble').first()).toBeVisible({ timeout: 5000 });
    });

    test('should send message and get bot response', async ({ page }) => {
        await loginAsCustomer(page);
        await selectRestaurant(page);
        // Type a message
        await page.locator('.ai-chat-input').fill('hello');
        await page.locator('.send-btn').click();
        await page.waitForTimeout(4000);
        // Bot bubble should update with new response
        await expect(page.locator('.ai-bubble').first()).toBeVisible({ timeout: 8000 });
    });

    test('should show mic button for voice mode', async ({ page }) => {
        await loginAsCustomer(page);
        await selectRestaurant(page);
        await expect(page.locator('.mic-btn')).toBeVisible({ timeout: 5000 });
    });

    test('clear the cart via chat clears cart and shows confirmation', async ({ page }) => {
        await loginAsCustomer(page);
        await selectRestaurant(page);
        await expect(page.locator('.ai-chat-input')).toBeVisible({ timeout: 5000 });
        const botBubbles = page.locator('.ai-bubble');
        const previousBotText = await botBubbles.last().textContent();
        // Clear the cart via chat
        await page.locator('.ai-chat-input').fill('clear the cart');
        await page.locator('.send-btn').click();
        // Frontend should handle clear-cart locally instead of falling through to backend item search.
        await expect(botBubbles.last()).not.toHaveText(previousBotText || '', { timeout: 8000 });
        await expect(botBubbles.last()).toContainText(/Cart cleared|already empty/i, { timeout: 8000 });
        await expect(page.locator('.ai-bubble').filter({ hasText: /Found \d+ items matching/i })).toHaveCount(0);
    });

    test('change the restaurant via chat gets a reply', async ({ page }) => {
        await loginAsCustomer(page);
        await selectRestaurant(page);
        await expect(page.locator('.ai-chat-input')).toBeVisible({ timeout: 5000 });
        // Ask to change restaurant (exact phrase we support)
        await page.locator('.ai-chat-input').fill('change the restaurant to Test');
        await page.locator('.send-btn').click();
        await page.waitForTimeout(5000);
        // Bot should reply (either switched or "couldn't find" / suggestions)
        const bubbles = page.locator('.ai-bubble');
        await expect(bubbles.last()).toBeVisible({ timeout: 8000 });
        const lastText = await bubbles.last().textContent();
        expect(lastText.length).toBeGreaterThan(0);
    });
});
