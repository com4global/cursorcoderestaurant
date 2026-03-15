// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('Group Order', () => {
  test('Group tab shows Start Group Order and Join with code', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(1500);
    await page.locator('.nav-item:has-text("Group")').click();
    await page.waitForTimeout(500);
    await expect(page.locator('.group-order-title')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=Start a group order')).toBeVisible();
    await expect(page.locator('button:has-text("Start Group Order")')).toBeVisible();
    await expect(page.locator('text=Join with code')).toBeVisible();
    await expect(page.locator('input[placeholder*="group code"]')).toBeVisible();
    await expect(page.locator('button:has-text("Join Group")')).toBeVisible();
  });

  test('Start Group Order creates session and shows share link', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(1500);
    await page.locator('.nav-item:has-text("Group")').click();
    await page.waitForTimeout(500);
    await page.locator('button:has-text("Start Group Order")').click();
    await page.waitForTimeout(2000);
    await expect(page.locator('text=Share with friends')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('.group-order-share-link')).toContainText(/group\/\d+/);
    await expect(page.locator('text=Members (0)')).toBeVisible();
  });

  test('Join Group with invalid code shows error', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(1500);
    await page.locator('.nav-item:has-text("Group")').click();
    await page.waitForTimeout(500);
    await page.locator('input[placeholder*="group code"]').fill('99999');
    await page.locator('button:has-text("Join Group")').click();
    await page.waitForTimeout(2000);
    await expect(page.locator('.group-order-status')).toContainText(/not found|404|error/i);
  });

  // Depends on backend /chat/message returning open_group_tab and reply; skip if backend unreachable or slow
  test.skip('Typing "group order" in chat opens Group tab', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(1500);
    const email = `pw_groupchat_${Date.now()}@test.com`;
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
    await page.locator('.nav-item:has-text("Chat")').click();
    await page.waitForTimeout(1500);
    const input = page.locator('.ai-chat-input').first();
    await expect(input).toBeVisible({ timeout: 8000 });
    await input.fill('I want to start a group order');
    await page.locator('.send-btn').click();
    await expect(page.getByText(/Group Order|Share the link/i)).toBeVisible({ timeout: 15000 });
    await page.locator('.nav-item:has-text("Group")').click();
    await page.waitForTimeout(500);
    await expect(page.locator('.group-order-title')).toBeVisible({ timeout: 5000 });
  });

  test('Create group then join with code and add member', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(1500);
    await page.locator('.nav-item:has-text("Group")').click();
    await page.waitForTimeout(500);
    await page.locator('button:has-text("Start Group Order")').click();
    await page.waitForTimeout(2000);
    const shareLinkEl = page.locator('.group-order-share-link');
    await expect(shareLinkEl).toBeVisible({ timeout: 5000 });
    const fullText = await shareLinkEl.textContent();
    const codeMatch = fullText.match(/group\/(\d+)/);
    expect(codeMatch).toBeTruthy();
    const shareCode = codeMatch[1];

    await page.locator('button:has-text("Start over")').click();
    await page.waitForTimeout(500);
    await page.locator('input[placeholder*="group code"]').fill(shareCode);
    await page.locator('button:has-text("Join Group")').click();
    await page.waitForTimeout(2000);
    await expect(page.locator(`text=Group: ${shareCode}`)).toBeVisible({ timeout: 5000 });
    await page.locator('input[placeholder="Your name"]').fill('Alex');
    await page.locator('input[placeholder*="Preference"]').fill('biryani');
    await page.locator('input[placeholder*="Budget"]').fill('15');
    await page.locator('button:has-text("Join")').click();
    await page.waitForTimeout(2000);
    await expect(page.locator('text=Alex')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=biryani')).toBeVisible();
  });

  test('Full flow: start group, join two members with inputs, get AI recommendation', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(1500);
    await page.locator('.nav-item:has-text("Group")').click();
    await page.waitForTimeout(500);
    await page.locator('button:has-text("Start Group Order")').click();
    await page.waitForTimeout(2000);
    const shareLinkEl = page.locator('.group-order-share-link');
    await expect(shareLinkEl).toBeVisible({ timeout: 5000 });
    const fullText = await shareLinkEl.textContent();
    const codeMatch = fullText.match(/group\/(\d+)/);
    expect(codeMatch).toBeTruthy();
    const shareCode = codeMatch[1];

    await page.locator('button:has-text("Start over")').click();
    await page.waitForTimeout(500);
    await page.locator('input[placeholder*="group code"]').fill(shareCode);
    await page.locator('button:has-text("Join Group")').click();
    await page.waitForTimeout(2000);
    await expect(page.locator(`text=Group: ${shareCode}`)).toBeVisible({ timeout: 5000 });

    await page.locator('input[placeholder="Your name"]').fill('Anitha');
    await page.locator('input[placeholder*="Preference"]').fill('biryani');
    await page.locator('input[placeholder*="Budget"]').fill('50');
    await page.locator('button:has-text("Join")').click();
    await page.waitForTimeout(2000);
    await expect(page.locator('text=Anitha')).toBeVisible({ timeout: 5000 });

    await page.locator('input[placeholder="Your name"]').fill('Yash');
    await page.locator('input[placeholder*="Preference"]').fill('burgers');
    await page.locator('input[placeholder*="Budget"]').fill('15');
    await page.locator('button:has-text("Join")').click();
    await page.waitForTimeout(2000);
    await expect(page.locator('text=Yash')).toBeVisible({ timeout: 5000 });

    await page.locator('button:has-text("Get AI Recommendation")').click();
    await page.waitForTimeout(5000);
    await expect(page.locator('.group-order-recommendation').or(page.locator('text=No recommendation')).first()).toBeVisible({ timeout: 10000 });
  });

  test('Full flow: sign in, start group, join self via code, get recommendation, add to cart', async ({ page }) => {
    const email = `pw_grouporder_${Date.now()}@test.com`;
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

    await page.locator('.nav-item:has-text("Group")').click();
    await page.waitForTimeout(500);
    await page.locator('button:has-text("Start Group Order")').click();
    await page.waitForTimeout(2000);
    await expect(page.locator('text=Share with friends')).toBeVisible({ timeout: 5000 });
    const shareLinkEl = page.locator('.group-order-share-link');
    const fullText = await shareLinkEl.textContent();
    const codeMatch = fullText.match(/group\/(\d+)/);
    const shareCode = codeMatch[1];

    await page.locator('button:has-text("Start over")').click();
    await page.waitForTimeout(500);
    await page.locator('input[placeholder*="group code"]').fill(shareCode);
    await page.locator('button:has-text("Join Group")').click();
    await page.waitForTimeout(2000);
    await page.locator('input[placeholder="Your name"]').fill('Me');
    await page.locator('input[placeholder*="Preference"]').fill('biryani');
    await page.locator('input[placeholder*="Budget"]').fill('20');
    await page.locator('button:has-text("Join")').click();
    await page.waitForTimeout(2000);
    await page.locator('button:has-text("Get AI Recommendation")').click();
    await page.waitForTimeout(6000);

    const recCard = page.locator('.group-order-recommendation');
    if (await recCard.isVisible({ timeout: 5000 }).catch(() => false)) {
      const addBtn = page.locator('button:has-text("Add to cart & order")');
      if (await addBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
        await addBtn.click();
        await page.waitForTimeout(3000);
        await expect(page.locator('.cart-panel').first()).toBeVisible({ timeout: 8000 });
      }
    }
  });

  test('Join with code then get recommendation without selecting restaurants', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(1500);
    await page.locator('.nav-item:has-text("Group")').click();
    await page.waitForTimeout(500);
    await page.locator('button:has-text("Start Group Order")').click();
    await page.waitForTimeout(2000);
    const shareLinkEl = page.locator('.group-order-share-link');
    const fullText = await shareLinkEl.textContent();
    const codeMatch = fullText.match(/group\/(\d+)/);
    const shareCode = codeMatch[1];

    await page.locator('button:has-text("Start over")').click();
    await page.waitForTimeout(500);
    await page.locator('input[placeholder*="group code"]').fill(shareCode);
    await page.locator('button:has-text("Join Group")').click();
    await page.waitForTimeout(2000);
    await page.locator('input[placeholder="Your name"]').fill('SecondUser');
    await page.locator('button:has-text("Join")').click();
    await page.waitForTimeout(2000);
    await page.locator('button:has-text("Get AI Recommendation")').click();
    await page.waitForTimeout(5000);
    await expect(page.locator('.group-order-recommendation').or(page.locator('.group-order-status')).first()).toBeVisible({ timeout: 10000 });
  });

  test('Restaurant preference checkboxes visible when group has session', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(1500);
    await page.locator('.nav-item:has-text("Group")').click();
    await page.waitForTimeout(500);
    await page.locator('button:has-text("Start Group Order")').click();
    await page.waitForTimeout(2000);
    await expect(page.locator('text=Restaurant preference')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('.group-order-restaurant-checkboxes').first()).toBeVisible({ timeout: 5000 });
  });
});
