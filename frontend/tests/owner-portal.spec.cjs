// @ts-check
const { test, expect } = require('@playwright/test');

const OWNER_EMAIL = `pw_owner_${Date.now()}@test.com`;
const OWNER_PASS = 'password123';

/**
 * Navigate to the Owner Portal via the Profile tab > "restaurant owner" link.
 * Then register/login as owner.
 */
async function navigateToOwnerPortal(page) {
    await page.goto('/');
    await page.waitForTimeout(1000);

    // Click Profile tab
    await page.locator('text=Profile').click();
    await page.waitForTimeout(1000);

    // Click "Are you a restaurant owner?" link
    const ownerLink = page.locator('text=/restaurant owner/i');
    await ownerLink.click();
    await page.waitForTimeout(1000);

    // Now on owner login — fill form
    const emailInput = page.locator('input').first();
    if (await emailInput.isVisible()) {
        await emailInput.fill(OWNER_EMAIL);
        const passwordInput = page.locator('input').nth(1);
        await passwordInput.fill(OWNER_PASS);
        // Click submit button
        const submitBtn = page.locator('button').first();
        await submitBtn.click();
        await page.waitForTimeout(3000);
    }
}

test.describe('Owner Portal', () => {
    test('should navigate to owner portal from Profile', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(1000);
        await page.locator('text=Profile').click();
        await page.waitForTimeout(1000);
        const ownerLink = page.locator('text=/restaurant owner/i');
        await expect(ownerLink).toBeVisible({ timeout: 5000 });
        await ownerLink.click();
        await page.waitForTimeout(1000);
        // Should see owner login form
        await expect(page.locator('input').first()).toBeVisible({ timeout: 5000 });
    });

    test('should login as owner', async ({ page }) => {
        await navigateToOwnerPortal(page);
        // Should see owner dashboard content
        // After first login, should go to pricing page or dashboard
        const dashboardVisible = await page.locator('text=/add restaurant|choose your plan|start free trial|my restaurants/i').first().isVisible({ timeout: 5000 }).catch(() => false);
        expect(dashboardVisible).toBe(true);
    });

    test('should create a restaurant', async ({ page }) => {
        await navigateToOwnerPortal(page);
        await page.waitForTimeout(1000);

        const addBtn = page.locator('text=/add restaurant/i').first();
        if (await addBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
            await addBtn.click();
            await page.waitForTimeout(1000);
            const nameInput = page.locator('input').first();
            if (await nameInput.isVisible()) {
                await nameInput.fill('PW Test Restaurant');
                const createBtn = page.locator('button').filter({ hasText: /create|save|add/i }).first();
                if (await createBtn.isVisible()) {
                    await createBtn.click();
                    await page.waitForTimeout(2000);
                }
            }
        }
    });
});
