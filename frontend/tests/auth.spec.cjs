// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('Customer App', () => {
    test('should load landing page', async ({ page }) => {
        await page.goto('/');
        await expect(page).toHaveTitle(/RestaurantAI/i);
    });

    test('should show bottom navigation tabs', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(1000);
        await expect(page.locator('text=Home')).toBeVisible();
        await expect(page.locator('text=Chat')).toBeVisible();
        await expect(page.locator('text=Orders')).toBeVisible();
        await expect(page.locator('text=Profile')).toBeVisible();
    });

    test('should display restaurant cards', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(2000);
        const orderNow = page.locator('text=Order Now');
        await expect(orderNow).toBeVisible({ timeout: 5000 });
    });

    test('should have search functionality', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(1000);
        const searchInput = page.locator('input[placeholder*="Search"]');
        await expect(searchInput).toBeVisible();
        await searchInput.fill('test');
        await page.waitForTimeout(1000);
    });

    test('should navigate to Profile tab', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(1000);
        await page.locator('text=Profile').click();
        await page.waitForTimeout(1000);
        const hasAuth = await page.locator('text=Sign in').first().isVisible().catch(() => false);
        expect(hasAuth).toBe(true);
    });

    test('should show owner portal link in Profile', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(1000);
        await page.locator('text=Profile').click();
        await page.waitForTimeout(1000);
        // Should show "Are you a restaurant owner?" link
        const ownerLink = page.locator('text=/restaurant owner/i');
        await expect(ownerLink).toBeVisible({ timeout: 5000 });
    });
});
