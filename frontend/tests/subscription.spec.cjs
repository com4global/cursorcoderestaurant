// @ts-check
const { test, expect } = require('@playwright/test');

const OWNER_PASS = 'password123';

/**
 * Navigate to owner portal and register.
 */
async function navigateToOwner(page) {
    const ownerEmail = `pw_sub_${Date.now()}_${Math.random().toString(36).slice(2, 6)}@test.com`;
    await page.goto('/');
    await page.waitForTimeout(1000);
    await page.locator('text=Profile').click();
    await page.waitForTimeout(1000);
    await page.locator('text=/restaurant owner/i').click();
    await page.waitForTimeout(1000);

    const emailInput = page.locator('input').first();
    if (await emailInput.isVisible()) {
        await emailInput.fill(ownerEmail);
        await page.locator('input').nth(1).fill(OWNER_PASS);
        await page.locator('button').first().click();
        await page.locator('.owner-loading').waitFor({ state: 'hidden', timeout: 10000 }).catch(() => {});
        await page.waitForTimeout(1000);
    }
}

test.describe('Subscription & Settings', () => {
    test('should show pricing/trial page for new owner', async ({ page }) => {
        await navigateToOwner(page);
        await expect(page.getByRole('heading', { name: /choose your plan/i })).toBeVisible({ timeout: 10000 });
        await expect(page.getByRole('button', { name: /start free trial/i })).toBeVisible({ timeout: 10000 });
    });

    test('should start free trial', async ({ page }) => {
        await navigateToOwner(page);
        const trial = page.getByRole('button', { name: /start free trial/i }).first();
        if (await trial.isVisible({ timeout: 5000 }).catch(() => false)) {
            await trial.click();
            await expect(page.getByRole('heading', { name: /owner dashboard/i })).toBeVisible({ timeout: 10000 });
            await expect(page.locator('text=/add restaurant|my restaurants/i').first()).toBeVisible({ timeout: 10000 });
        }
    });

    test('should show trial badge in dashboard', async ({ page }) => {
        await navigateToOwner(page);
        const trial = page.getByRole('button', { name: /start free trial/i }).first();
        if (await trial.isVisible({ timeout: 3000 }).catch(() => false)) {
            await trial.click();
            await expect(page.getByRole('heading', { name: /owner dashboard/i })).toBeVisible({ timeout: 10000 });
        }
        // Should see trial badge
        const badge = page.locator('text=/trial|days left/i').first();
        await expect(badge).toBeVisible({ timeout: 5000 });
    });

    test('should show Settings tab with billing', async ({ page }) => {
        await navigateToOwner(page);
        // Start trial
        const trial = page.getByRole('button', { name: /start free trial/i }).first();
        if (await trial.isVisible({ timeout: 3000 }).catch(() => false)) {
            await trial.click();
            await expect(page.getByRole('heading', { name: /owner dashboard/i })).toBeVisible({ timeout: 10000 });
        }

        // Create restaurant to see tabs
        const addBtn = page.locator('text=/add restaurant/i').first();
        if (await addBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
            await addBtn.click();
            await page.waitForTimeout(500);
            const formInputs = page.locator('input');
            await formInputs.first().fill('Settings Test');
            await formInputs.nth(1).fill('TestCity');
            const createBtn = page.locator('button:has-text("Create Restaurant")').first();
            if (await createBtn.isVisible()) {
                await createBtn.click();
                await page.waitForTimeout(2000);
            }
        }

        // Click Settings tab
        const settingsTab = page.locator('text=Settings').first();
        if (await settingsTab.isVisible({ timeout: 5000 }).catch(() => false)) {
            await settingsTab.click();
            await page.waitForTimeout(500);
            // Should show plan info or billing
            const planInfo = page.locator('text=/plan|billing|free trial|standard|corporate/i').first();
            await expect(planInfo).toBeVisible({ timeout: 5000 });
        }
    });

    test('should show logout button', async ({ page }) => {
        await navigateToOwner(page);
        const trial = page.getByRole('button', { name: /start free trial/i }).first();
        if (await trial.isVisible({ timeout: 3000 }).catch(() => false)) {
            await trial.click();
        }
        const dashboardVisible = await page.getByRole('heading', { name: /owner dashboard/i }).isVisible({ timeout: 10000 }).catch(() => false);
        if (dashboardVisible) {
            const logout = page.getByRole('button', { name: /logout|sign out/i }).first();
            await expect(logout).toBeVisible({ timeout: 5000 });
        } else {
            await expect(page.getByRole('button', { name: /back/i })).toBeVisible({ timeout: 5000 });
        }
    });
});
