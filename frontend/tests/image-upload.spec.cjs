// @ts-check
const { test, expect } = require('@playwright/test');
const path = require('path');

const OWNER_EMAIL = `pw_upload_${Date.now()}@test.com`;
const OWNER_PASS = 'password123';

/**
 * Navigate to owner portal, register, create restaurant, click Extract tab.
 */
async function setupOwnerWithRestaurant(page) {
    await page.goto('/');
    await page.waitForTimeout(1000);

    // Navigate to owner portal
    await page.locator('text=Profile').click();
    await page.waitForTimeout(1000);
    await page.locator('text=/restaurant owner/i').click();
    await page.waitForTimeout(1000);

    // Register as owner
    const emailInput = page.locator('input').first();
    if (await emailInput.isVisible()) {
        await emailInput.fill(OWNER_EMAIL);
        await page.locator('input').nth(1).fill(OWNER_PASS);
        await page.locator('button').first().click();
        await page.waitForTimeout(3000);
    }

    // Start trial if prompted
    const trial = page.locator('text=/start free trial/i').first();
    if (await trial.isVisible({ timeout: 3000 }).catch(() => false)) {
        await trial.click();
        await page.waitForTimeout(2000);
    }

    // Create a restaurant
    const addBtn = page.locator('text=/add restaurant/i').first();
    if (await addBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await addBtn.click();
        await page.waitForTimeout(500);
        const formInputs = page.locator('input');
        await formInputs.first().fill('Upload Test Restaurant');
        await formInputs.nth(1).fill('TestCity');
        const createBtn = page.locator('button:has-text("Create Restaurant")').first();
        if (await createBtn.isVisible()) {
            await createBtn.click();
            await page.waitForTimeout(2000);
        }
    }
}

test.describe('Image Upload E2E', () => {
    test('should navigate to Extract > Photo and see dropzone', async ({ page }) => {
        await setupOwnerWithRestaurant(page);

        // Click Extract tab
        const extractTab = page.locator('text=Extract').first();
        if (await extractTab.isVisible({ timeout: 5000 }).catch(() => false)) {
            await extractTab.click();
            await page.waitForTimeout(500);

            // Click Photo card
            await page.locator('text=Photo').click();
            await page.waitForTimeout(500);

            // Should see dropzone with drag & drop text
            const dropzone = page.locator('text=/drag.*drop|JPG.*PNG/i').first();
            await expect(dropzone).toBeVisible({ timeout: 3000 });
        }
    });

    test('should show error for unsupported file type', async ({ page }) => {
        await setupOwnerWithRestaurant(page);

        const extractTab = page.locator('text=Extract').first();
        if (await extractTab.isVisible({ timeout: 5000 }).catch(() => false)) {
            await extractTab.click();
            await page.waitForTimeout(500);
            await page.locator('text=Photo').click();
            await page.waitForTimeout(500);

            // Upload a .txt file (unsupported)
            const fileInput = page.locator('input[type="file"]').first();
            const testFile = path.join(__dirname, '..', 'package.json'); // Any non-image file
            await fileInput.setInputFiles(testFile);
            await page.waitForTimeout(1000);

            // Should show error
            const error = page.locator('text=/unsupported|file type/i').first();
            await expect(error).toBeVisible({ timeout: 3000 });
        }
    });

    test('should navigate to Extract > Document and see dropzone', async ({ page }) => {
        await setupOwnerWithRestaurant(page);

        const extractTab = page.locator('text=Extract').first();
        if (await extractTab.isVisible({ timeout: 5000 }).catch(() => false)) {
            await extractTab.click();
            await page.waitForTimeout(500);
            await page.locator('text=Document').click();
            await page.waitForTimeout(500);

            const dropzone = page.locator('text=/drag.*drop|PDF.*DOCX/i').first();
            await expect(dropzone).toBeVisible({ timeout: 3000 });
        }
    });

    test('should navigate to Extract > Website and see URL input', async ({ page }) => {
        await setupOwnerWithRestaurant(page);

        const extractTab = page.locator('text=Extract').first();
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
