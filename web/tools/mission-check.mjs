import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

// Real Windows records and trained models, without generated fixtures or new training.
const baseUrl = (process.env.IGNIS_BROWSER_URL ?? 'http://127.0.0.1:5173').replace(/\/$/, '');
const output = path.resolve('artifacts/mission');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.IGNIS_BROWSER_PATH || undefined,
  args:
    process.platform === 'linux'
      ? ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']
      : [],
});
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 });
const page = await context.newPage();
page.setDefaultTimeout(60_000);
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));
page.on('console', (entry) => {
  if (entry.type() === 'error') errors.push(entry.text());
});
const evidence = {
  checked_at: new Date().toISOString(),
  base_url: baseUrl,
  checks: [],
  screenshots: [],
  errors,
};
const record = (name, details = {}) => evidence.checks.push({ name, passed: true, ...details });
const digest = (bytes) => createHash('sha256').update(bytes).digest('hex');
const canvas = () => page.locator('.mission-canvas canvas');
async function screenshot(name) {
  await page.screenshot({ path: path.join(output, name) });
  evidence.screenshots.push(name);
}
async function ready() {
  await page.locator('.mission-viewport[data-field-status="available"]').waitFor();
  await page.locator('.mission-loading').waitFor({ state: 'hidden' });
  await page.locator('.mission-render-status').waitFor({ state: 'hidden' });
}
async function setTime(value) {
  await page.getByLabel('Temps de la scène', { exact: true }).evaluate((input, next) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, String(next));
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }, value);
  await page.waitForTimeout(350);
}

try {
  await page.goto(baseUrl, { waitUntil: 'networkidle' });
  await ready();
  assert.equal(
    await page.getByRole('button', { name: 'Mission', exact: true }).getAttribute('aria-current'),
    'page',
  );
  assert.equal(await page.getByLabel('Environnement de mission').inputValue(), 'soyuz');
  assert.equal(await page.locator('.mission-viewport').getAttribute('data-camera'), 'pov');
  const runId = await page.getByLabel('Simulation enregistrée', { exact: true }).inputValue();
  const run = await (await page.request.get(`${baseUrl}/api/runs/${runId}`)).json();
  assert.equal(run.config.scene_id, 'soyuz');
  assert.equal(run.config.mode, 'physics');
  assert.ok(run.result.frames.some((frame) => frame.smoke_kg_m3?.some((value) => value > 0)));
  record('mission_opens_in_pov_with_real_soyuz_fds', { run_id: runId, frames: run.result.frames.length });
  await screenshot('mission-pov.png');
  assert.ok(await page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight + 1));
  record('desktop_stage_fills_available_window_without_document_scroll');

  const scale = await page.locator('.mission-scale-values').innerText();
  await setTime(0);
  const start = digest(await canvas().screenshot());
  await setTime(19);
  const hot = digest(await canvas().screenshot());
  await setTime(50);
  const late = digest(await canvas().screenshot());
  assert.notEqual(start, hot);
  assert.notEqual(hot, late);
  assert.equal(await page.locator('.mission-scale-values').innerText(), scale);
  record('spatial_heat_smoke_changes_with_recording_and_keeps_fixed_scale', { start, hot, late, scale });

  await setTime(19);
  await page.getByRole('button', { name: 'Lire la scène', exact: true }).click();
  await page.waitForTimeout(1400);
  await page.getByRole('button', { name: 'Mettre la lecture en pause', exact: true }).click();
  const paused = Number(await page.getByLabel('Temps de la scène', { exact: true }).inputValue());
  assert.ok(paused > 19.5);
  await page.waitForTimeout(350);
  assert.equal(Number(await page.getByLabel('Temps de la scène', { exact: true }).inputValue()), paused);
  record('playback_advances_and_pause_freezes_recorded_time');

  const originalPov = digest(await canvas().screenshot());
  await canvas().focus();
  await page.keyboard.down('ArrowRight');
  await page.waitForTimeout(250);
  await page.keyboard.up('ArrowRight');
  await page.waitForTimeout(150);
  assert.notEqual(digest(await canvas().screenshot()), originalPov);
  await page.getByRole('button', { name: 'Recentrer la vue mission', exact: true }).click();
  record('occupant_camera_moves_with_keyboard_and_resets');

  await page.getByRole('button', { name: 'Vue orbitale', exact: true }).click();
  await setTime(19);
  await screenshot('mission-orbit-heatmap.png');
  for (const name of ['Fumée', 'Température', 'Ventilation', 'Cabine seule', 'Fumée thermique']) {
    await page.getByRole('button', { name, exact: true }).click();
    if (name !== 'Cabine seule') await ready();
  }
  await page.getByRole('button', { name: 'Vue de dessus', exact: true }).click();
  assert.equal(await page.locator('.mission-viewport').getAttribute('data-camera'), 'top');
  await screenshot('mission-top.png');
  record('all_layers_and_three_camera_views_work');

  await page.getByLabel('Environnement de mission').selectOption('cargo');
  await ready();
  const cargoId = await page.getByLabel('Simulation enregistrée', { exact: true }).inputValue();
  const cargo = await (await page.request.get(`${baseUrl}/api/runs/${cargoId}`)).json();
  assert.equal(cargo.config.scene_id, 'cargo');
  assert.ok(cargo.result.frames.length > 0);
  assert.match(await page.locator('.mission-provenance').innerText(), /modèle ML/);
  record('scene_switch_selects_spatial_replay_and_labels_ml_origin', { run_id: cargoId });

  await page.getByLabel('Environnement de mission').selectOption('soyuz');
  await ready();
  await page.getByRole('button', { name: 'Modifier le scénario', exact: true }).click();
  assert.equal(
    await page.getByRole('slider', { name: 'Vitesse d’entrée', exact: true }).inputValue(),
    String(run.config.airflow_m_s),
  );
  assert.equal(
    await page.getByRole('slider', { name: 'Puissance du feu imposée', exact: true }).inputValue(),
    String(run.config.ignition_power_w),
  );
  record('laboratory_receives_the_displayed_replay_configuration');
  await page.getByRole('button', { name: 'Mission', exact: true }).click();
  await ready();

  await page.getByRole('button', { name: 'Avant allumage', exact: true }).click();
  assert.equal(await page.locator('.mission-viewport').getAttribute('data-layer'), 'scene');
  assert.equal(await page.locator('.mission-component-map button').count(), 4);
  await page.getByLabel('Courant de référence', { exact: true }).fill('6');
  const resultResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/prevention/analyze') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Calculer la prévision', exact: true }).click();
  const response = await resultResponse;
  assert.equal(response.ok(), true, await response.text());
  const analysis = await response.json();
  await page.locator('.mission-evidence').waitFor();
  assert.ok(analysis.components.some((item) => item.learned_forecast.length));
  assert.equal(analysis.config.current_a, 6);
  assert.ok(analysis.components.every((item) => item.ignition_probability === null));
  assert.match(await page.locator('.mission-evidence').innerText(), /SOURCE DU DÉLAI · HORS NASA/);
  await page.getByRole('button', { name: 'Vue orbitale', exact: true }).click();
  await setTime(2);
  await screenshot('mission-prevention.png');
  record('preignition_uses_real_ml_without_smoke_or_probability', { analysis_id: analysis.id });

  await page.locator('[data-mission-component]').last().click();
  assert.match(await page.locator('.mission-inspector').innerText(), /Non estimé/);
  assert.doesNotMatch(await page.locator('.mission-evidence').innerText(), /SOURCE DU DÉLAI/);
  record('unsupported_battery_remains_unknown_with_context_sources');
  await page.locator('[data-mission-component]').first().click();
  await page.getByRole('button', { name: 'Paramètres & courbes détaillées', exact: true }).click();
  assert.equal(await page.locator('#prevention-current_a').inputValue(), '6');
  await page.locator('#prevention-horizon_s').fill('8');
  await page.getByRole('button', { name: 'Mission', exact: true }).click();
  assert.equal(
    await page.getByRole('button', { name: 'Avant allumage', exact: true }).getAttribute('aria-pressed'),
    'true',
  );
  assert.equal(await page.getByLabel('Courant de référence', { exact: true }).inputValue(), '6');
  assert.match(await page.locator('.mission-facts').innerText(), /8,0 s/);
  record('advanced_prevention_parameters_return_to_the_immersive_view');

  await page.getByRole('button', { name: 'Fumée & chaleur', exact: true }).click();
  await ready();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'POV équipage', exact: true }).click();
  await setTime(19);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
  await screenshot('mission-mobile.png');
  await page.getByRole('button', { name: 'Masquer le panneau', exact: true }).click();
  assert.equal(await page.locator('.mission-inspector').count(), 0);
  await page.getByRole('button', { name: 'Afficher le panneau', exact: true }).click();
  assert.equal(await page.locator('.mission-inspector').count(), 1);
  record('mobile_layout_has_no_horizontal_overflow_and_inspector_toggles');

  assert.deepEqual(errors, []);
  evidence.passed = true;
} catch (error) {
  evidence.passed = false;
  evidence.failure = error.stack ?? String(error);
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  await writeFile(path.join(output, 'verification.json'), JSON.stringify(evidence, null, 2) + '\n');
  console.log(
    JSON.stringify({
      passed: evidence.passed,
      checks: evidence.checks.length,
      failure: evidence.failure,
      errors,
    }),
  );
  await browser.close();
}
