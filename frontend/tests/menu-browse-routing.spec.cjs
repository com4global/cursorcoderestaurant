// @ts-check
const { test, expect } = require('@playwright/test');

async function loginAsCustomer(page) {
    const email = `pw_browse_${Date.now()}_${Math.random().toString(36).slice(2, 6)}@test.com`;
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

test.describe('Menu browse routing', () => {
    test('selected restaurant browse phrase shows categories instead of adding an item', async ({ page }) => {
        await loginAsCustomer(page);

        const restaurantCard = page.locator('.restaurant-card-v').first();
        await expect(restaurantCard).toBeVisible({ timeout: 10000 });
        await restaurantCard.click();

        await expect(page.locator('.ai-chat-input')).toBeVisible({ timeout: 10000 });
        await expect(page.locator('.cat-pill').first()).toBeVisible({ timeout: 10000 });

        await page.locator('.ai-chat-input').fill("give me some today's special menus");
        await page.locator('.send-btn').click();

        await expect(page.locator('.cat-pill').first()).toBeVisible({ timeout: 10000 });
        await expect(page.locator('.menu-browser-title')).toContainText(/Choose a category|Soups|Today's Specials/i, { timeout: 10000 });
        await expect(page.locator('.ai-bubble').filter({ hasText: /Added to your order/i })).toHaveCount(0);
    });

    test('selected restaurant spicy suggestion phrase stays in browse mode instead of adding to cart', async ({ page }) => {
        await loginAsCustomer(page);

        const restaurantCard = page.locator('.restaurant-card-v').first();
        await expect(restaurantCard).toBeVisible({ timeout: 10000 });
        await restaurantCard.click();

        await expect(page.locator('.ai-chat-input')).toBeVisible({ timeout: 10000 });
        await expect(page.locator('.cat-pill').first()).toBeVisible({ timeout: 10000 });

        await page.locator('.ai-chat-input').fill('I want some special spicy item today can you give me some option');
        await page.locator('.send-btn').click();

        await expect(page.locator('.cat-pill').first()).toBeVisible({ timeout: 10000 });
        await expect(page.locator('.ai-bubble').last()).toContainText(/Pick a category and I will show you some options/i, { timeout: 10000 });
        await expect(page.locator('.ai-bubble').filter({ hasText: /Added to your order/i })).toHaveCount(0);
    });

    test('nearby special-item discovery phrase shows comparison options in global chat', async ({ page }) => {
        await loginAsCustomer(page);

        await page.locator('.nav-item:has-text("Chat")').click();
        await page.waitForTimeout(1000);

        await expect(page.locator('.chat-header-title')).toContainText('RestaurantAI', { timeout: 10000 });
        await expect(page.locator('.ai-chat-input')).toBeVisible({ timeout: 10000 });

        await page.locator('.ai-chat-input').fill('give me something special item near by ?');
        await page.locator('.send-btn').click();

        await expect(page.locator('.price-compare-card')).toBeVisible({ timeout: 10000 });
        await expect(page.locator('.compare-order-btn').first()).toBeVisible({ timeout: 10000 });
    });
});