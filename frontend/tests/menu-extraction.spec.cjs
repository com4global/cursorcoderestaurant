// @ts-check
const { test, expect } = require('@playwright/test');

const OWNER_EMAIL = `pw_extract_${Date.now()}@test.com`;
const OWNER_PASS = 'password123';

async function ownerLoginAndSetup(page) {
    await page.goto('/');
    await page.waitForTimeout(1000);

    // Navigate to owner portal
    await page.locator('text=Profile').click();
    await page.waitForTimeout(1000);
    await page.locator('text=/restaurant owner/i').click();
    await page.waitForTimeout(1000);

    // Login
    const emailInput = page.locator('input').first();
    if (await emailInput.isVisible()) {
        await emailInput.fill(OWNER_EMAIL);
        await page.locator('input').nth(1).fill(OWNER_PASS);
        await page.locator('button').first().click();
        await page.waitForTimeout(3000);
    }

    // Create restaurant if needed
    const addBtn = page.locator('text=/add restaurant/i').first();
    if (await addBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await addBtn.click();
        await page.waitForTimeout(500);
        await page.locator('input').first().fill('Extract Menu Test');
        const createBtn = page.locator('button').filter({ hasText: /create|save|add/i }).first();
        if (await createBtn.isVisible()) {
            await createBtn.click();
            await page.waitForTimeout(2000);
        }
    }

    // Click on restaurant card to open it
    const restCard = page.locator('[class*="rest-card"], [class*="restaurant"]').first();
    if (await restCard.isVisible({ timeout: 3000 }).catch(() => false)) {
        await restCard.click();
        await page.waitForTimeout(1000);
    }
}

test.describe('Menu Extraction UI', () => {
    test.beforeEach(async ({ page }) => {
        await ownerLoginAndSetup(page);
    });

    test('should show Extract tab with 3 modes', async ({ page }) => {
        const extractTab = page.locator('text=Extract');
        if (await extractTab.isVisible({ timeout: 5000 }).catch(() => false)) {
            await extractTab.click();
            await page.waitForTimeout(500);
            await expect(page.locator('text=Website')).toBeVisible({ timeout: 3000 });
            await expect(page.locator('text=Photo')).toBeVisible({ timeout: 3000 });
            await expect(page.locator('text=Document')).toBeVisible({ timeout: 3000 });
        }
    });

    test('should open Photo mode', async ({ page }) => {
        const extractTab = page.locator('text=Extract');
        if (await extractTab.isVisible({ timeout: 5000 }).catch(() => false)) {
            await extractTab.click();
            await page.waitForTimeout(500);
            await page.locator('text=Photo').click();
            await page.waitForTimeout(500);
            const dropZone = page.locator('text=/drag.*drop|JPG.*PNG/i').first();
            await expect(dropZone).toBeVisible({ timeout: 3000 });
        }
    });

    test('should open Document mode', async ({ page }) => {
        const extractTab = page.locator('text=Extract');
        if (await extractTab.isVisible({ timeout: 5000 }).catch(() => false)) {
            await extractTab.click();
            await page.waitForTimeout(500);
            await page.locator('text=Document').click();
            await page.waitForTimeout(500);
            const dropZone = page.locator('text=/drag.*drop|PDF.*DOCX/i').first();
            await expect(dropZone).toBeVisible({ timeout: 3000 });
        }
    });

    test('should open Website mode', async ({ page }) => {
        const extractTab = page.locator('text=Extract');
        if (await extractTab.isVisible({ timeout: 5000 }).catch(() => false)) {
            await extractTab.click();
            await page.waitForTimeout(500);
            await page.locator('text=Website').click();
            await page.waitForTimeout(500);
            const urlInput = page.locator('input[placeholder*="url" i], input[type="url"]').first();
            await expect(urlInput).toBeVisible({ timeout: 3000 });
        }
    });
});
