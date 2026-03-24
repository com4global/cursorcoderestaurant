// @ts-check
const { test, expect } = require('@playwright/test');

async function createOwnerRestaurantWithoutMenu(page) {
    const ownerEmail = `pw_owner_onboard_${Date.now()}_${Math.random().toString(36).slice(2, 6)}@test.com`;
    const restaurantName = `PW Onboarding Rest ${Date.now()}`;

    await page.goto('/');
    await page.waitForTimeout(1200);
    await page.locator('.nav-item:has-text("Profile")').click();
    await page.waitForTimeout(500);
    await page.locator('text=/restaurant owner/i').click();
    await page.waitForTimeout(800);

    await page.locator('input').first().fill(ownerEmail);
    await page.locator('input').nth(1).fill('password123');
    await page.locator('button').first().click();
    await page.waitForTimeout(2500);

    const startTrialButton = page.locator('button').filter({ hasText: /start free trial/i }).first();
    if (await startTrialButton.isVisible({ timeout: 3000 }).catch(() => false)) {
        await startTrialButton.click();
        await page.waitForTimeout(2500);
    }

    const addRestaurantButton = page.locator('button').filter({ hasText: /add restaurant/i }).first();
    await expect(addRestaurantButton).toBeVisible({ timeout: 10000 });
    await addRestaurantButton.click();

    const inputs = page.locator('.owner-form input');
    await inputs.nth(0).fill(restaurantName);
    await inputs.nth(1).fill('TestCity');
    await page.locator('button').filter({ hasText: /create restaurant/i }).click();
    await page.waitForTimeout(2000);

    return restaurantName;
}

async function loginAsCustomer(page) {
    await page.evaluate(() => {
        localStorage.clear();
        sessionStorage.clear();
    });
    await page.context().clearCookies();

    const email = `pw_customer_onboard_${Date.now()}_${Math.random().toString(36).slice(2, 6)}@test.com`;
    await page.goto('/');
    await page.waitForTimeout(1200);
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

test.describe('Restaurant onboarding message', () => {
    test('customer sees onboarding message for restaurant with no menu yet', async ({ page }) => {
        const restaurantName = await createOwnerRestaurantWithoutMenu(page);

        const logoutButton = page.locator('button').filter({ hasText: /logout/i }).first();
        if (await logoutButton.isVisible({ timeout: 3000 }).catch(() => false)) {
            await logoutButton.click();
            await page.waitForTimeout(1000);
        }

        await loginAsCustomer(page);

        const restaurantCard = page.locator('.restaurant-card-v').filter({ hasText: restaurantName }).first();
        await expect(restaurantCard).toBeVisible({ timeout: 10000 });
        await restaurantCard.click();

        await expect(page.locator('.onboarding-notice-card')).toBeVisible({ timeout: 10000 });
        await expect(page.locator('.onboarding-notice-title')).toContainText(/joining RestaurantAI/i, { timeout: 10000 });
        await expect(page.locator('.onboarding-notice-body')).toContainText(/restaurant owner to add the full menu/i, { timeout: 10000 });
    });
});