// @ts-check
const { test, expect } = require('@playwright/test');

async function loginAsCustomer(page) {
    const email = `pw_compare_${Date.now()}_${Math.random().toString(36).slice(2, 6)}@test.com`;
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

async function goToGlobalChat(page) {
    await page.locator('.nav-item:has-text("Chat")').click();
    await page.waitForTimeout(1000);
    await expect(page.locator('.chat-header-title')).toContainText('RestaurantAI', { timeout: 10000 });
    await expect(page.locator('.ai-chat-input')).toBeVisible({ timeout: 10000 });
}

test.describe('Price Comparison', () => {
    test('should show comparison card for "cheapest biryani"', async ({ page }) => {
        await loginAsCustomer(page);
        await goToGlobalChat(page);
        await page.locator('.ai-chat-input').fill('cheapest biryani');
        await page.locator('.send-btn').click();
        await page.waitForTimeout(3000);
        await expect(page.locator('.price-compare-card')).toBeVisible({ timeout: 8000 });
    });

    test('should show comparison card for "compare chicken"', async ({ page }) => {
        await loginAsCustomer(page);
        await goToGlobalChat(page);
        await page.locator('.ai-chat-input').fill('compare chicken');
        await page.locator('.send-btn').click();
        await page.waitForTimeout(3000);
        await expect(page.locator('.price-compare-card')).toBeVisible({ timeout: 8000 });
    });

    test('comparison card should have Order buttons', async ({ page }) => {
        await loginAsCustomer(page);
        await goToGlobalChat(page);
        await page.locator('.ai-chat-input').fill('cheapest biryani');
        await page.locator('.send-btn').click();
        await page.waitForTimeout(3000);
        await expect(page.locator('.compare-order-btn').first()).toBeVisible({ timeout: 8000 });
    });

    test('comparison card should show best value footer', async ({ page }) => {
        await loginAsCustomer(page);
        await goToGlobalChat(page);
        await page.locator('.ai-chat-input').fill('cheapest biryani');
        await page.locator('.send-btn').click();
        await page.waitForTimeout(3000);
        await expect(page.locator('.compare-footer')).toBeVisible({ timeout: 8000 });
    });

    test('should show comparison options for vague combo request phrasing', async ({ page }) => {
        await loginAsCustomer(page);
        await goToGlobalChat(page);
        await page.locator('.ai-chat-input').fill('give me some special combos today');
        await page.locator('.send-btn').click();
        await page.waitForTimeout(3000);
        await expect(page.locator('.price-compare-card')).toBeVisible({ timeout: 10000 });
        await expect(page.locator('.compare-order-btn').first()).toBeVisible({ timeout: 10000 });
    });

    test('should show comparison options for misspelled dish queries', async ({ page }) => {
        await loginAsCustomer(page);
        await goToGlobalChat(page);
        await page.locator('.ai-chat-input').fill('briyani');
        await page.locator('.send-btn').click();
        await page.waitForTimeout(3000);
        await expect(page.locator('.price-compare-card')).toBeVisible({ timeout: 10000 });
        await expect(page.locator('.compare-order-btn').first()).toBeVisible({ timeout: 10000 });
    });
});
