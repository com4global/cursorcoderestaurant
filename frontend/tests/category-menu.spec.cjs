// @ts-check
const { test, expect } = require('@playwright/test');

/**
 * Category → menu items: selecting a category must show menu items.
 * Regression: fixes 500 on /chat/message and /categories/:id/items when selecting
 * a restaurant then a category; categories and menus must load.
 *
 * Run: ensure backend (port 8000) and frontend (port 5173) are up, then:
 *   npx playwright install chromium   # once
 *   npx playwright test tests/category-menu.spec.cjs
 */

test.describe('Category loads menu items', () => {
    test('select restaurant → categories load → click category → menu items load (full flow)', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(2000);
        const card = page.locator('.restaurant-card-v').first();
        await expect(card).toBeVisible({ timeout: 10000 });
        await card.click();
        await page.waitForTimeout(3000);
        await expect(page.locator('.cat-pill').first()).toBeVisible({ timeout: 10000 });
        await page.locator('.cat-pill').first().click();
        await page.waitForTimeout(3000);
        await expect(page.locator('.menu-item').first()).toBeVisible({ timeout: 10000 });
        await expect(page.locator('.menu-item-name').first()).toBeVisible({ timeout: 5000 });
        await expect(page.locator('.menu-item-price').first()).toBeVisible({ timeout: 5000 });
    });

    test('guest: select restaurant then category shows menu items', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(2000);
        const card = page.locator('.restaurant-card-v').first();
        await expect(card).toBeVisible({ timeout: 10000 });
        await card.click();
        await page.waitForTimeout(3000);
        const firstPill = page.locator('.cat-pill').first();
        await expect(firstPill).toBeVisible({ timeout: 10000 });
        firstPill.click();
        await page.waitForTimeout(3000);
        await expect(page.locator('.menu-item').first()).toBeVisible({ timeout: 10000 });
    });

    test('guest: menu item has name and price', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(2000);
        await page.locator('.restaurant-card-v').first().click();
        await page.waitForTimeout(3000);
        await page.locator('.cat-pill').first().click();
        await page.waitForTimeout(3000);
        await expect(page.locator('.menu-item-name').first()).toBeVisible({ timeout: 10000 });
        await expect(page.locator('.menu-item-price').first()).toBeVisible({ timeout: 5000 });
    });

    test('logged-in: select restaurant then category shows menu items', async ({ page }) => {
        const email = `pw_cat_${Date.now()}_${Math.random().toString(36).slice(2, 6)}@test.com`;
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

        await page.locator('.restaurant-card-v').first().click();
        await page.waitForTimeout(3000);
        await page.locator('.cat-pill').first().click();
        await page.waitForTimeout(3000);
        await expect(page.locator('.menu-item').first()).toBeVisible({ timeout: 10000 });
    });
});
