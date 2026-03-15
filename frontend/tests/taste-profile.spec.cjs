// @ts-check
const { test, expect } = require('@playwright/test');

async function loginAsCustomer(page) {
    const email = `pw_taste_${Date.now()}_${Math.random().toString(36).slice(2, 6)}@test.com`;
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
}

test.describe('Taste Profile tab', () => {
    test('should show Taste tab in nav and open taste page', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(1500);
        await expect(page.locator('.nav-item:has-text("Taste")')).toBeVisible({ timeout: 5000 });
        await page.locator('.nav-item:has-text("Taste")').click();
        await page.waitForTimeout(1000);
        await expect(page.locator('.taste-title:has-text("AI Flavor Profile")')).toBeVisible({ timeout: 5000 });
    });

    test('when not logged in, should prompt to sign in', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(1500);
        await page.locator('.nav-item:has-text("Taste")').click();
        await page.waitForTimeout(1000);
        await expect(page.locator('.taste-empty-text')).toContainText(/Sign in/i, { timeout: 5000 });
    });

    test('when logged in, should show preferences form and save', async ({ page }) => {
        await loginAsCustomer(page);
        await page.locator('.nav-item:has-text("Taste")').click();
        await page.waitForTimeout(2000);
        await expect(page.locator('.taste-section-title:has-text("Spice level")')).toBeVisible({ timeout: 8000 });
        await expect(page.locator('.taste-option-btn').first()).toBeVisible({ timeout: 5000 });
        await page.locator('.taste-option-btn:has-text("Spicy")').click();
        await page.waitForTimeout(300);
        await page.locator('.taste-save-btn').click();
        await page.waitForTimeout(2000);
        await expect(page.locator('.taste-section-title:has-text("Spice level")')).toBeVisible({ timeout: 5000 });
    });

    test('when logged in, should show Personalized picks section', async ({ page }) => {
        await loginAsCustomer(page);
        await page.locator('.nav-item:has-text("Taste")').click();
        await page.waitForTimeout(2000);
        await expect(page.locator('.taste-section-title:has-text("Personalized picks")')).toBeVisible({ timeout: 8000 });
    });
});
