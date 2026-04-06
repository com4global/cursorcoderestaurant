// @ts-check
const { test, expect } = require('@playwright/test');

async function injectOwnerAnalyticsMocks(page) {
    await page.addInitScript(() => {
        localStorage.setItem('token', 'pw-owner-token');
        localStorage.setItem('userRole', 'owner');
    });

    await page.route('**/restaurants**', async (route) => {
        const url = new URL(route.request().url());
        if (url.pathname === '/restaurants') {
            await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
            return;
        }
        await route.continue();
    });

    await page.route('**/nearby**', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    });

    await page.route('**/auth/me', async (route) => {
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ id: 91, email: 'owner@test.com', role: 'owner' }),
        });
    });

    await page.route('**/owner/subscription', async (route) => {
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ plan: 'pro', status: 'active', active: true, trial_end: null }),
        });
    });

    await page.route('**/owner/restaurants/11/analytics**', async (route) => {
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
                date_from: '2026-02-24',
                date_to: '2026-03-24',
                summary: {
                    total_revenue_cents: 452300,
                    order_count: 126,
                    avg_order_cents: 3590,
                },
                daily_revenue: [
                    { date: '2026-03-22', revenue: 120300, orders: 34 },
                    { date: '2026-03-23', revenue: 151000, orders: 41 },
                    { date: '2026-03-24', revenue: 181000, orders: 51 },
                ],
                top_items: [
                    { menu_item_id: 1, name: 'Chicken Biryani', quantity: 34, revenue: 51066 },
                ],
                orders_by_status: {
                    completed: 88,
                    preparing: 10,
                    ready: 8,
                    confirmed: 20,
                },
            }),
        });
    });

    await page.route('**/api/call-order/admin/summary', async (route) => {
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
                ttl_minutes: 1440,
                total_sessions: 18,
                active_sessions: 7,
                expired_sessions: 11,
                sessions_created_last_24h: 4,
                sessions_created_last_7d: 12,
                sessions_updated_last_24h: 9,
                oldest_active_updated_at: '2026-03-24T10:15:00Z',
                newest_active_updated_at: '2026-03-24T18:45:00Z',
            }),
        });
    });

    await page.route('**/owner/restaurants', async (route) => {
        const url = new URL(route.request().url());
        if (url.pathname === '/owner/restaurants') {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify([
                    {
                        id: 11,
                        name: 'A2B',
                        city: 'Chicago',
                        notification_email: 'owner@test.com',
                        notification_phone: '',
                    },
                ]),
            });
            return;
        }
        await route.continue();
    });
}

test.describe('Owner AI Call Analytics', () => {
    test('shows the AI Call retention card and trend counters inside Sales analytics', async ({ page }) => {
        await injectOwnerAnalyticsMocks(page);

        await page.goto('/');

        await expect(page.locator('text=A2B').first()).toBeVisible({ timeout: 10000 });
        await page.getByRole('button', { name: /sales/i }).click();

        await expect(page.locator('.sales-call-summary')).toBeVisible({ timeout: 10000 });
        await expect(page.locator('.sales-call-summary')).toContainText('AI Call Session Retention');
        await expect(page.locator('.sales-call-summary')).toContainText('Persisted Sessions');
        await expect(page.locator('.sales-call-summary')).toContainText('18');
        await expect(page.locator('.sales-call-summary')).toContainText('Active Inside TTL');
        await expect(page.locator('.sales-call-summary')).toContainText('7');
        await expect(page.locator('.sales-call-summary')).toContainText('Expired Pending Cleanup');
        await expect(page.locator('.sales-call-summary')).toContainText('11');
        await expect(page.locator('.sales-call-summary')).toContainText('Created 24h');
        await expect(page.locator('.sales-call-summary')).toContainText('4');
        await expect(page.locator('.sales-call-summary')).toContainText('Created 7d');
        await expect(page.locator('.sales-call-summary')).toContainText('12');
        await expect(page.locator('.sales-call-summary')).toContainText('Touched 24h');
        await expect(page.locator('.sales-call-summary')).toContainText('9');
        await expect(page.locator('.sales-call-summary')).toContainText('TTL 1440 min');
    });
});