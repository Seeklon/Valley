import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const base = (process.env.POV_URL ?? 'http://127.0.0.1:5182').replace(/\/$/, '');
const output = path.resolve(process.env.POV_EVIDENCE ?? 'artifacts/browser');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.BROWSER_PATH || undefined, headless: true,
  args: process.platform === 'linux' ? ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] : [],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1, reducedMotion: 'reduce' });
page.setDefaultTimeout(90_000);
const errors = [], renderErrors = [], writes = [], checks = [], screenshots = [];
page.on('pageerror', error => errors.push(error.message));
page.on('console', message => { if (message.type() === 'error' && /THREE|WebGL|shader/i.test(message.text())) renderErrors.push(message.text()); });
page.on('request', request => { if (!['GET', 'HEAD'].includes(request.method())) writes.push(request.url()); });
const record = (name, details = {}) => { checks.push({ name, ...details }); console.log(JSON.stringify({ passed: name, ...details })); };
const shot = async name => { await page.screenshot({ path: path.join(output, name) }); screenshots.push(name); };
const root = () => page.locator('#prediction-room');
async function ready(family, expand = true) {
  await page.waitForFunction(expected => {
    const el = document.querySelector('#prediction-room');
    return el?.dataset.state === 'ready' && !el.hidden && (!expected || el.dataset.caseId?.startsWith(expected)) && el.dataset.triangles > 0;
  }, family);
  assert.equal(await root().locator('canvas').count(), 1);
  if (expand && !(await page.locator('#pars').isVisible())) await page.locator('#ml-toggle').click();
}
const indexResponse = await page.request.get(`${base}/poc/iss/index.json`);
assert.ok(indexResponse.ok());
const index = await indexResponse.json();
async function selected() {
  const id = await root().getAttribute('data-case-id');
  const entry = index.cases.find(item => item.id === id);
  assert.ok(entry);
  const response = await page.request.get(`${base}/poc/iss/${entry.url.replace(/^\.\//, '').replace(/^\/poc\/iss\//, '')}`);
  const bytes = await response.body();
  assert.equal(createHash('sha256').update(bytes).digest('hex'), entry.sha256);
  assert.equal(await root().getAttribute('data-model-sha'), index.model.weights_sha256);
  return { data: JSON.parse(bytes), entry };
}
async function frameAt(n) {
  await page.locator('#ml-time').evaluate((input, value) => { input.value = String(value); input.dispatchEvent(new Event('input', { bubbles: true })); }, n);
}
async function checkCounts(data, display, n) {
  await page.selectOption('#ml-display', display);
  await frameAt(n);
  const frame = data.frames[n];
  for (const channel of ['heat', 'smoke']) {
    const truth = channel === 'heat' ? frame.hotspot_truth : frame.smoke_truth;
    const predicted = channel === 'heat' ? frame.predicted_hot_mask : frame.predicted_smoke_mask;
    const mask = frame[`${channel}_valid_mask`];
    let count = 0;
    for (let i = 0; i < mask.length; i++) if (mask[i] && frame[`${channel}_score`][i] != null) {
      const actual = truth[i], pred = predicted[i];
      if (display === 'prediction' ? pred : display === 'reference' ? actual : actual || pred) count++;
    }
    assert.equal(Number(await root().getAttribute(`data-${channel}-count`)), count);
  }
  assert.equal(Number(await root().getAttribute('data-time-s')), frame.time_s);
}

try {
  await page.goto(`${base}/?nogl&hub&open=prev`, { waitUntil: 'domcontentloaded' });
  await ready('habitat-cargo', false);
  assert.equal(await page.locator('#pars').isVisible(), false);
  assert.equal(await page.locator('#panel').evaluate(el => el.classList.contains('open')), false);
  assert.equal(await page.locator('#ml-toggle').getAttribute('aria-expanded'), 'false');
  await shot('00-unobstructed-pov.png');
  await page.locator('#ptab').click();
  assert.equal(await page.locator('#panel').evaluate(el => el.classList.contains('open')), true);
  await page.locator('#ml-toggle').click();
  assert.equal(await page.locator('#panel').evaluate(el => el.classList.contains('open')), false);
  assert.equal(await page.locator('#pars').isVisible(), true);
  record('Investigations and prediction controls start closed and open independently without overlapping');
  await shot('01-site-with-prediction.png');
  const { data } = await selected();
  record('Original site opens its prevention room with the verified cargo scene', { case: data.id, model: index.model.weights_sha256 });
  for (const display of ['prediction', 'reference', 'errors']) {
    await checkCounts(data, display, 0);
    await checkCounts(data, display, data.frames.length - 1);
  }
  record('Heat and smoke counts match the actual saved masks at both ends of the timeline');
  await page.selectOption('#ml-display', 'prediction');
  await page.locator('#ml-heat').uncheck();
  assert.equal(await root().getAttribute('data-heat-visible'), 'false');
  await page.locator('#ml-heat').check();
  await page.locator('#ml-smoke').uncheck();
  assert.equal(await root().getAttribute('data-smoke-visible'), 'false');
  await page.locator('#ml-smoke').check();
  await frameAt(0);
  await page.locator('[data-ml-action="play"]').click();
  await page.waitForFunction(() => +document.querySelector('#prediction-room').dataset.timeS > 0);
  await page.locator('[data-ml-action="play"]').click();
  record('Layer controls and time playback work');
  const preservedTime = await root().getAttribute('data-time-s');
  await page.locator('[data-ml-action="close"]').click();
  assert.equal(await page.locator('#pars').isVisible(), false);
  await page.locator('#ml-toggle').click();
  assert.equal(await root().getAttribute('data-time-s'), preservedTime);
  assert.equal(await root().getAttribute('data-case-id'), data.id);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#pars').isVisible(), false);
  record('Closing and reopening controls preserves the selected scenario and timeline; Escape closes the drawer');
  const canvas = root().locator('canvas');
  const position = await root().getAttribute('data-camera-position');
  await canvas.focus();
  for (const key of ['ArrowUp', 'ArrowRight', 'ArrowDown']) await page.keyboard.press(key);
  await page.waitForFunction(before => document.querySelector('#prediction-room').dataset.cameraPosition !== before, position);
  const direction = await root().getAttribute('data-camera-direction');
  const beforeDirection = direction.split(',').map(Number);
  await page.mouse.move(780, 300); await page.mouse.down(); await page.mouse.move(840, 300, { steps: 5 }); await page.mouse.up();
  await page.waitForFunction(before => document.querySelector('#prediction-room').dataset.cameraDirection !== before, direction);
  const afterRight = (await root().getAttribute('data-camera-direction')).split(',').map(Number);
  assert.ok(afterRight[0] * -beforeDirection[2] + afterRight[2] * beforeDirection[0] > 0.1, 'Dragging right must look right');
  await page.mouse.move(780, 300); await page.mouse.down(); await page.mouse.move(780, 255, { steps: 5 }); await page.mouse.up();
  await page.waitForFunction(y => +document.querySelector('#prediction-room').dataset.cameraDirection.split(',')[1] > y + 0.05, afterRight[1]);
  await page.locator('#ml-toggle').click();
  await page.locator('[data-ml-action="reset"]').click();
  record('POV drag looks right when dragged right and up when dragged up; movement and reset work');
  await page.locator('[data-ml-action="close"]').click();
  await page.locator('#ml-view-toggle').click();
  assert.equal(await root().getAttribute('data-view'), 'exterior');
  assert.equal(await page.locator('#pars').isVisible(), false);
  await shot('exterior-without-panels.png');
  await page.locator('#ml-view-toggle').click();
  assert.equal(await root().getAttribute('data-view'), 'pov');
  await page.locator('#ml-toggle').click();
  record('The persistent Exterior view button opens the whole compartment and returns to POV without opening controls');
  const rooms = { prev: 'habitat-cargo', det: 'iss-node', sup: 'iss-service', fun: 'iss-laboratory', si: 'habitat-central-racks' };
  for (const [room, family] of Object.entries(rooms)) {
    if (room !== 'prev') { await page.locator(`[data-go="${room}"]`).click(); await ready(family); }
    await selected();
    await shot(`room-${room}.png`);
    await page.locator('[data-ml-action="view"]').click();
    await shot(`room-${room}-overview.png`);
    await page.locator('[data-ml-action="view"]').click();
    record(`Room ${room} uses ${family} and its own predictions`);
  }
  await page.selectOption('#ml-family', 'habitat-capsule');
  await ready('habitat-capsule');
  await shot('room-capsule.png');
  const controls = index.cases.filter(entry => entry.family === 'habitat-capsule' && entry.gravity_g < 0.01 && entry.id === index.example_cases.cold_control);
  assert.ok(controls.length);
  await page.selectOption('#ml-scenario', controls[0].id);
  await page.waitForFunction(id => document.querySelector('#prediction-room').dataset.caseId === id && document.querySelector('#prediction-room').dataset.state === 'ready', controls[0].id);
  const control = await selected();
  assert.equal(control.data.conditions.power_w, 0);
  await checkCounts(control.data, 'prediction', control.data.frames.length - 1);
  record('Sixth geometry and no-fire control use actual model outputs');
  await page.locator('#back').click();
  await page.waitForFunction(() => document.querySelector('#prediction-room').hidden);
  assert.equal(await page.locator('#pars').isVisible(), false);
  await shot('station-preserved.png');
  record('Return to the original station and navigation');
  await page.goto(`${base}/?nogl&hub&env=earth&open=det`, { waitUntil: 'domcontentloaded' });
  await ready('iss-node');
  const earth = await selected();
  const hasEarth = index.cases.some(entry => Math.abs(entry.gravity_g - 1) < 0.02);
  if (hasEarth) {
    assert.equal(earth.data.conditions.gravity_g, 1);
    assert.equal(await root().getAttribute('data-geometry-only'), 'false');
  } else {
    assert.equal(await root().getAttribute('data-geometry-only'), 'true');
    assert.equal(await root().getAttribute('data-heat-visible'), 'false');
    assert.equal(await root().getAttribute('data-smoke-visible'), 'false');
    assert.equal(await page.locator('#ml-display').isDisabled(), true);
    assert.match(await page.locator('#pars').innerText(), /Earth · 1 g · predictions unavailable/);
  }
  await shot('earth-room.png');
  record(hasEarth ? 'Earth selects a genuine 1 g case' : 'Unavailable Earth predictions are disabled, with the correct gravity label');
  await page.goto(`${base}/?nogl&hub&env=moon&open=fun`, { waitUntil: 'domcontentloaded' });
  await ready('iss-laboratory');
  assert.equal(await root().getAttribute('data-geometry-only'), 'true');
  assert.equal(await root().getAttribute('data-heat-visible'), 'false');
  assert.equal(await root().getAttribute('data-smoke-visible'), 'false');
  assert.equal(await page.locator('#ml-display').isDisabled(), true);
  await shot('moon-geometry-only.png');
  record('Unavailable lunar predictions are not substituted by microgravity predictions');
  await page.setViewportSize({ width: 390, height: 844 });
  await shot('mobile.png');
  assert.equal(await page.locator('#pars').isVisible(), true);
  const closeBox = await page.locator('[data-ml-action="close"]').boundingBox();
  assert.ok(closeBox && closeBox.y >= 0 && closeBox.y + closeBox.height < 844);
  await page.locator('[data-ml-action="close"]').click();
  assert.equal(await page.locator('#ml-view-toggle').isVisible(), true);
  await page.locator('#ptab').click();
  await page.locator('#panel [data-close]').click();
  assert.equal(await page.locator('#panel').evaluate(el => el.classList.contains('open')), false);
  await shot('mobile-unobstructed.png');
  record('Mobile preserves navigation and usable controls');
  assert.deepEqual(errors, []); assert.deepEqual(renderErrors, []); assert.deepEqual(writes, []);
  record('No JavaScript errors, no writes, no training or simulation jobs');
} finally {
  await writeFile(path.join(output, 'report.json'), JSON.stringify({ url: base, model: index.model, cases: index.cases.length, checks, errors, renderErrors, writes, screenshots }, null, 2));
  await browser.close();
}
