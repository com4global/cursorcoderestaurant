// @ts-check
const { test, expect } = require('@playwright/test');

async function loginAsCustomer(page) {
    const email = `pw_fb_${Date.now()}_${Math.random().toString(36).slice(2, 6)}@test.com`;
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

test.describe('Post-Order Feedback', () => {
    test('Orders tab has History and shows feedback UI or empty state', async ({ page }) => {
        await loginAsCustomer(page);
        await page.locator('.nav-item:has-text("Orders")').click();
        await page.waitForTimeout(1000);
        await page.locator('.orders-tab:has-text("History")').click();
        await page.waitForTimeout(1000);
        await expect(
            page.locator('text=/No past orders|Delivered|How was your order/i').first()
        ).toBeVisible({ timeout: 5000 });
    });

    test('feedback card shows stars and submit when present', async ({ page }) => {
        await loginAsCustomer(page);
        await page.locator('.nav-item:has-text("Orders")').click();
        await page.waitForTimeout(1000);
        await page.locator('.orders-tab:has-text("History")').click();
        await page.waitForTimeout(1000);
        const feedbackCard = page.locator('.feedback-card').first();
        const hasEligibleOrder = await feedbackCard.isVisible({ timeout: 3000 }).catch(() => false);
        if (hasEligibleOrder) {
            await expect(page.locator('.feedback-stars')).toBeVisible();
            await expect(page.locator('.feedback-submit-btn')).toBeVisible();
        }
    });
});
