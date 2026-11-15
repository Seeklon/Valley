import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: true,
  executablePath: process.env.BROWSER_PATH || undefined,
  args: process.platform === 'linux' ? ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] : [],
});
const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
page.setDefaultTimeout(120_000);
const errors = [], checks = [], skipped = [];
page.on('pageerror', error => errors.push(error.message));
const record = name => { checks.push(name); console.log(JSON.stringify({ passed: name })); };
const ready = async () => {
  await page.waitForFunction(() => document.querySelector('#prediction-room')?.dataset.state === 'ready');
  if (!(await page.locator('#pars').isVisible())) await page.locator('#ml-toggle').click();
};
await mkdir('artifacts/browser-edges', { recursive: true });
try {
  const base = process.env.POV_URL ?? 'http://127.0.0.1:5182';
  if (process.env.POV_LIVE_WEBGL === '1') {
    await page.setViewportSize({ width: 640, height: 480 });
  await page.goto(`${base}/?gl&hub&open=fun`, { waitUntil: 'domcontentloaded' });
  await ready();
  assert.equal(await page.locator('#gl').isVisible(), true);
  await page.screenshot({ path: 'artifacts/browser-edges/live-exterior-pov.png' });
  await page.locator('#back').click();
  await page.waitForFunction(() => document.querySelector('#prediction-room').hidden);
  await page.screenshot({ path: 'artifacts/browser-edges/live-station.png' });
  record('The original live WebGL exterior can enter and leave a prediction room');
    await page.setViewportSize({ width: 1280, height: 900 });
  } else skipped.push('Forced live exterior WebGL: enable POV_LIVE_WEBGL=1 on a GPU-capable browser.');
  const nested = process.env.POV_NESTED_URL ?? 'http://127.0.0.1:5183/mission';
  const requests = [];
  page.on('request', request => { if (request.url().includes('/poc/iss/')) requests.push(request.url()); });
  await page.goto(`${nested}/?nogl&hub&open=det`, { waitUntil: 'domcontentloaded' });
  await ready();
  assert.ok(requests.length >= 2);
  assert.ok(requests.every(url => url.startsWith(`${nested}/poc/iss/`)));
  record('Prediction assets load correctly below /mission/');
  // Inject an unavailable export, never fabricated predictions, to check the failure state.
  await page.route('**/poc/iss/cases/**', route => route.abort('failed'));
  await page.selectOption('#ml-family', 'habitat-capsule');
  await page.waitForFunction(() => document.querySelector('#prediction-room').dataset.state === 'error');
  assert.equal(await page.locator('#prediction-room').getAttribute('data-case-id'), null);
  assert.equal(await page.locator('#ml-time').count(), 0);
  await page.screenshot({ path: 'artifacts/browser-edges/unavailable-export.png' });
  await page.unroute('**/poc/iss/cases/**');
  await page.locator('[data-go="fun"]').click();
  await ready();
  record('An unavailable export clears the previous predictions and a new room recovers');
  // Supersede one real request immediately: an old response must not overwrite the new room.
  await page.locator('#ml-family').evaluate(select => {
    select.value = 'habitat-cargo'; select.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await page.locator('[data-go="si"]').click();
  await ready();
  await page.waitForFunction(() => document.querySelector('#prediction-room').dataset.caseId?.startsWith('habitat-central-racks'));
  record('Rapid navigation never binds an earlier scene response to the new room');
  assert.deepEqual(errors, []);
} finally {
  await writeFile('artifacts/browser-edges/report.json', JSON.stringify({ checks, errors, skipped }, null, 2));
  await browser.close();
}
