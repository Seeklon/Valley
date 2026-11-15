import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

// Check the real exported model predictions. No fixture, route interception,
// model training, or FDS request is created by this browser verification.
const base = (process.env.IGNIS_BROWSER_URL ?? 'http://127.0.0.1:5173').replace(/\/$/, '');
const output = path.resolve(process.env.IGNIS_POC_EVIDENCE ?? 'artifacts/hotspot-poc');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.IGNIS_BROWSER_PATH || undefined,
  args:
    process.platform === 'linux'
      ? ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']
      : [],
});
const page = await browser.newPage({ viewport: { width: 1600, height: 1050 }, deviceScaleFactor: 1 });
page.setDefaultTimeout(60_000);
const errors = [],
  writes = [],
  checks = [],
  screenshots = [];
page.on('pageerror', (error) => errors.push(error.message));
page.on('request', (request) => {
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method())) {
    writes.push({ method: request.method(), path: new URL(request.url()).pathname });
  }
});
const record = (name, evidence = {}) => {
  checks.push({ name, passed: true, ...evidence });
  console.log(JSON.stringify({ check: name, passed: true }));
};
async function json(url) {
  const response = await page.request.get(url.startsWith('http') ? url : base + url);
  assert.equal(response.ok(), true, `${url}: ${response.status()}`);
  return response.json();
}
const root = () => page.locator('[data-hotspot-poc]');
async function ready(id) {
  await page.waitForFunction((expected) => {
    const el = document.querySelector('[data-hotspot-poc]');
    return el?.getAttribute('data-case-id') === expected && el.getAttribute('data-time-s') !== '';
  }, id);
  await root().locator('canvas').waitFor();
  await page.waitForTimeout(350);
  assert.equal(await root().locator('.poc-render-error').count(), 0);
}
async function select(entry) {
  await page.getByLabel('Partition des données', { exact: true }).selectOption(entry.split);
  await page.getByLabel('Scénario du POC', { exact: true }).selectOption(entry.id);
  await ready(entry.id);
}
async function frame(number, expectedTime) {
  await page.getByLabel('Instant de comparaison', { exact: true }).evaluate((input, value) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, String(value));
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }, number);
  await page.waitForFunction(
    (time) => Number(document.querySelector('[data-hotspot-poc]')?.getAttribute('data-time-s')) === time,
    expectedTime,
  );
  await page.waitForTimeout(250);
}
async function screenshot(name) {
  await page.screenshot({ path: path.join(output, name), fullPage: true });
  screenshots.push(name);
}
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');
const caseUrl = (value) => (value.startsWith('/') ? value : `/poc/${value}`);
let index;
try {
  index = await json('/poc/hotspots.json');
  assert.equal(index.schema_version, 'hotspot-poc-1');
  assert.ok(index.model.weights_sha256?.match(/^[a-f0-9]{64}$/));
  assert.equal(index.model.heat_delta_c, 5);
  assert.equal(index.cases.length, 200, 'All compact cases must remain accessible.');
  assert.equal(index.cases.filter((item) => item.split === 'test').length, 40);
  await page.goto(`${base}/#poc`, { waitUntil: 'networkidle' });
  await root().waitFor();
  const initial = await root().getAttribute('data-case-id');
  await ready(initial);
  assert.equal(await page.locator('[data-poc-view="reference"]').count(), 1);
  assert.equal(await page.locator('[data-poc-view="prediction"]').count(), 1);
  assert.ok((await root().innerText()).includes('probabilité d’incendie'));
  record('real_model_export_and_two_synchronized_views', { model: index.model, cases: index.cases.length });

  const representative =
    index.cases.find((item) => item.id === index.example_cases?.representative) ??
    index.cases.find((item) => item.split === 'validation' && item.metrics.tp > 0);
  assert.ok(representative);
  await select(representative);
  const data = await json(caseUrl(representative.url));
  let peak = 0,
    peakTemperature = -Infinity;
  data.frames.forEach((item, i) => {
    const temperature = Math.max(...item.temperature_c.filter(Number.isFinite));
    if (temperature > peakTemperature) {
      peakTemperature = temperature;
      peak = i;
    }
  });
  await frame(0, data.frames[0].time_s);
  const firstHash = hash(await root().locator('canvas').screenshot());
  await frame(peak, data.frames[peak].time_s);
  const peakHash = hash(await root().locator('canvas').screenshot());
  if (peak > 0 && representative.metrics.tp + representative.metrics.fn > 0) {
    assert.notEqual(firstHash, peakHash, 'Observed heat must visibly change the replay.');
  }
  record('timeline_uses_real_times_and_changes_render', {
    id: data.id,
    time_s: data.frames[peak].time_s,
    firstHash,
    peakHash,
  });
  await screenshot('poc-representative.png');

  await page.getByRole('button', { name: 'Dessus', exact: true }).click();
  await page.waitForTimeout(300);
  const topHash = hash(await root().locator('canvas').screenshot());
  assert.notEqual(topHash, peakHash, 'Shared camera must change the two views.');
  await page.getByRole('button', { name: 'Orbite', exact: true }).click();
  await page.getByLabel('Erreurs ML', { exact: true }).uncheck();
  await page.waitForTimeout(250);
  await screenshot('poc-detections.png');
  await page.getByLabel('Erreurs ML', { exact: true }).check();
  record('shared_camera_and_error_layer_work');

  for (const [key, name] of [
    ['failure', 'poc-failure.png'],
    ['cold_control', 'poc-cold-control.png'],
  ]) {
    const entry = index.cases.find((item) => item.id === index.example_cases?.[key]);
    assert.ok(entry, `${key} example must be accessible.`);
    await select(entry);
    const replay = await json(caseUrl(entry.url));
    await frame(replay.frames.length - 1, replay.frames.at(-1).time_s);
    await screenshot(name);
    record(`honest_${key}_case_accessible`, { id: entry.id, metrics: entry.metrics });
  }

  const historical = index.cases.find((item) => item.split === 'test');
  await select(historical);
  assert.ok((await root().innerText()).includes('historique déjà consulté'));
  record('historical_test_is_labeled');

  await select(representative);
  await frame(peak, data.frames[peak].time_s);
  await page.setViewportSize({ width: 1100, height: 800 });
  await page.waitForTimeout(300);
  assert.ok(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2),
    'Laptop layout must not overflow horizontally.',
  );
  await screenshot('poc-laptop.png');
  record('laptop_layout_fits');

  await page.getByRole('button', { name: 'Sources NASA', exact: true }).first().click();
  await page.getByRole('button', { name: 'Sources NASA', exact: true }).first().waitFor();
  assert.equal(writes.length, 0, 'Exploring the POC must not submit FDS, training, or interpretation jobs.');
  assert.deepEqual(errors, []);
  record('read_only_demo_without_javascript_errors_or_new_compute');
} finally {
  await writeFile(
    path.join(output, 'browser-report.json'),
    JSON.stringify(
      {
        checked_at: new Date().toISOString(),
        base,
        model_id: index?.model.id,
        checks,
        errors,
        writes,
        screenshots,
      },
      null,
      2,
    ) + '\n',
  );
  await browser.close();
}
