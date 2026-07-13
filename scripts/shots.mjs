/**
 * Capture real product screenshots for the marketing site.
 *
 * Runs inside the Playwright container ON the compose network, so it reaches the live
 * apps at their service names (admin-ui:4600, portal:4700, marketing:4900). Logs into
 * the real ISP console with the seeded dev account and shoots each screen against the
 * seeded demo data — so these are genuine screens of the product, not mockups.
 *
 * Every shot is best-effort: one failing screen must not lose the others.
 */
import { chromium } from 'playwright';

const OUT = '/media';
const LOGIN = { phone: '254700000000', password: 'admin12345' };
const VIEWPORT = { width: 1440, height: 900 };

const shots = [];
async function shoot(page, file, note) {
  try {
    await page.waitForTimeout(1200); // let fonts + data settle
    await page.screenshot({ path: `${OUT}/${file}`, animations: 'disabled' });
    shots.push(file);
    console.log(`  ✓ ${file} — ${note}`);
  } catch (e) {
    console.log(`  ✗ ${file} — ${e.message}`);
  }
}

async function clickNav(page, label) {
  // The console is a state-tab SPA; nav items are buttons with the label text.
  try {
    await page.getByText(label, { exact: false }).first().click({ timeout: 5000 });
    await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
  } catch {
    console.log(`  (couldn't click nav "${label}")`);
  }
}

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 2 });
const page = await ctx.newPage();

// ---- ISP console (logged in) ------------------------------------------------------
console.log('ISP console:');
await page.goto('http://admin-ui:4600/', { waitUntil: 'networkidle' });
await page.waitForTimeout(1000);
// Log in.
try {
  await page.fill('input[autocomplete="username"], input[type="text"], input[type="tel"]', LOGIN.phone);
  await page.fill('input[type="password"]', LOGIN.password);
  await page.click('button[type="submit"]');
  await page.waitForLoadState('networkidle', { timeout: 12000 }).catch(() => {});
  await page.waitForTimeout(2500);
} catch (e) {
  console.log('  login failed:', e.message);
}

await shoot(page, 'console-dashboard.png', 'dashboard (hero)');

await clickNav(page, 'Wallet');
await shoot(page, 'wallet-ledger.png', 'wallet');

await clickNav(page, 'Reports');
await shoot(page, 'reports.png', 'reports');

await clickNav(page, 'Clients');
await shoot(page, 'pppoe-clients.png', 'PPPoE clients');

await clickNav(page, 'Network');
await shoot(page, 'router-health.png', 'routers');

// ---- Captive portal (public) ------------------------------------------------------
console.log('Captive portal:');
const portal = await ctx.newPage();
await portal.goto('http://portal:4700/?router=1', { waitUntil: 'networkidle' }).catch(() => {});
await shoot(portal, 'stk-push.png', 'portal payment screen');

// ---- Marketing signup wizard (public) ---------------------------------------------
console.log('Signup:');
const signup = await ctx.newPage();
await signup.goto('http://marketing:4900/signup', { waitUntil: 'networkidle' }).catch(() => {});
await shoot(signup, 'go-live.png', 'signup wizard');

await browser.close();
console.log(`\nCaptured ${shots.length} screenshots.`);
