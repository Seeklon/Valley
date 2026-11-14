import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

// Real incident model, real assets and ONE explicitly launched FDS calculation.
// No network fixtures, route interception, training or pre-existing run substitution.
const baseUrl = (process.env.IGNIS_BROWSER_URL ?? 'http://127.0.0.1:5173').replace(/\/$/, '');
const timeout = Number(process.env.IGNIS_FDS_TIMEOUT_MS ?? 20 * 60_000);
assert.ok(Number.isFinite(timeout) && timeout > 0, 'IGNIS_FDS_TIMEOUT_MS must be positive.');
const output = path.resolve('artifacts/incidents');
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
const requests = [];
let createdRunId = null;
let completed = false;
page.on('pageerror', (error) => errors.push(error.message));
page.on('request', (request) => {
  if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/runs')
    requests.push(request.postDataJSON());
});
const evidence = {
  checked_at: new Date().toISOString(),
  base_url: baseUrl,
  checks: [],
  screenshots: [],
  errors,
};
const record = (name, details = {}) => {
  evidence.checks.push({ name, passed: true, ...details });
  console.log(JSON.stringify({ check: name, passed: true }));
};
const digest = (bytes) => createHash('sha256').update(bytes).digest('hex');
const numericKeys = [
  'gravity_g',
  'airflow_m_s',
  'oxygen_percent',
  'ignition_power_w',
  'ignition_duration_s',
  'duration_s',
];
const viewport = () => page.locator('.mission-viewport');
const canvas = () => page.locator('.mission-canvas canvas');
const componentButton = (id) => page.locator(`[data-propagation-component="${id}"]`);
const format = (value, decimals = 1) =>
  Number.isFinite(value)
    ? value.toLocaleString('fr-FR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    : '—';
const physicalConditions = (config) =>
  Object.fromEntries(Object.entries(config).filter(([key]) => key !== 'model_id'));
async function getJson(route) {
  const response = await page.request.get(`${baseUrl}${route}`);
  assert.equal(response.ok(), true, `${route}: ${await response.text()}`);
  return response.json();
}
async function screenshot(name) {
  await page.screenshot({ path: path.join(output, name), fullPage: true });
  evidence.screenshots.push(name);
}
async function ready() {
  await canvas().waitFor();
  await page.locator('.mission-render-status').waitFor({ state: 'hidden' });
}
async function pause() {
  const button = page.getByRole('button', { name: 'Mettre la propagation en pause', exact: true });
  if (await button.count()) await button.click();
}
async function setTime(time) {
  await pause();
  await page.getByLabel('Instant de propagation', { exact: true }).evaluate((input, value) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, String(value));
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }, time);
  await page.waitForTimeout(400);
}
async function readConditions() {
  const config = {
    scene_id: await page.locator('#propagation-scene').inputValue(),
    incident_type: await page.locator('#propagation-incident').inputValue(),
    component_id: await page
      .locator('[data-propagation-component][aria-pressed="true"]')
      .getAttribute('data-propagation-component'),
  };
  for (const key of numericKeys) config[key] = Number(await page.locator(`#propagation-${key}`).inputValue());
  return config;
}
async function assertConsequenceCards(result) {
  const values = result.summary.consequences;
  const keys = ['heat_peak_c', 'smoke_peak_mg_m3', 'exposed_equipment_count', 'critical_exposed_count'];
  for (const [index, key] of keys.entries()) {
    const actual = await page.locator('.propagation-metrics strong').nth(index).innerText();
    assert.ok(actual.includes(format(values[key], index < 2 ? 1 : 0)), `${key}: ${actual}`);
  }
  const passages = page.locator('.propagation-facts > div').filter({ hasText: 'Passages exposés' });
  assert.equal((await passages.locator('dd').innerText()).trim(), format(values.passages_exposed_count, 0));
}
async function inspectFields(result, prefix) {
  assert.ok(result.frames.length > 1, 'Temporal observations must actually exist.');
  await pause();
  const fields = [
    ['temperature', 'Température', 'temperature_c'],
    ['smoke', 'Fumée', 'smoke_kg_m3'],
    ['airflow', 'Ventilation', 'velocity_m_s'],
  ];
  for (const [layer, label, key] of fields) {
    const available = result.frames.some((frame) => frame[key]?.some(Number.isFinite));
    const button = page.getByRole('button', { name: label, exact: true });
    assert.equal(await button.isDisabled(), !available, `${key}: availability must follow the result.`);
    if (available) {
      await button.click();
      await page.locator(`.mission-viewport[data-layer="${layer}"]`).waitFor();
      await ready();
    }
  }
  await page.getByRole('button', { name: 'Température', exact: true }).click();
  const ordered = result.frames.map((frame) => ({
    time: frame.time_s,
    peak: Math.max(...(frame.temperature_c ?? []).filter(Number.isFinite)),
  }));
  const peak = ordered.reduce((best, frame) => (frame.peak > best.peak ? frame : best), ordered[0]);
  const scale = await page.locator('.mission-scale-values').innerText();
  await setTime(ordered[0].time);
  const startHash = digest(await canvas().screenshot());
  await setTime(peak.time);
  const hotHash = digest(await canvas().screenshot());
  assert.equal(await page.locator('.mission-scale-values').innerText(), scale);
  if (peak.time > ordered[0].time && peak.peak > 26 && peak.peak > ordered[0].peak + 1)
    assert.notEqual(startHash, hotHash, 'A changing observed temperature field must change the image.');
  record(`${prefix}_reads_real_fields_and_fixed_temporal_scale`, {
    frames: result.frames.length,
    peak,
    start_hash: startHash,
    peak_hash: hotHash,
    scale,
  });
  await screenshot(`${prefix}-temperature.png`);
}

try {
  const [health, catalog, scenes] = await Promise.all([
    getJson('/api/health'),
    getJson('/api/incidents/catalog'),
    getJson('/api/scenes'),
  ]);
  assert.equal(catalog.model?.available, true, 'The trained incident model must be genuinely loaded.');
  assert.equal(health.capabilities?.physics, true, 'A real FDS solver is required.');
  assert.notEqual(health.worker_available, false);
  const components = catalog.components.filter((entry) => entry.scene_id === 'soyuz');
  assert.ok(components.length >= 2, 'Two distinct annotated Soyuz sites are required.');
  const second = components[1];
  const scene = scenes.scenes.find((entry) => entry.id === 'soyuz');
  assert.ok(scene?.asset_url);
  const asset = await page.request.get(new URL(scene.asset_url, baseUrl).href);
  assert.equal(asset.ok(), true);
  assert.equal((await asset.body()).toString('ascii', 0, 4), 'glTF');
  evidence.runtime = health;
  evidence.model_id = catalog.model.id;

  await page.goto(baseUrl, { waitUntil: 'networkidle' });
  await page.locator('[data-propagation-page="prediction"]').waitFor();
  await page.waitForFunction(() => document.querySelector('#propagation-scene')?.value === 'soyuz');
  await ready();
  assert.equal(
    await page.getByRole('button', { name: 'Prédiction', exact: true }).getAttribute('aria-current'),
    'page',
  );
  assert.equal(await page.locator('[data-propagation-component]').count(), components.length);
  assert.equal(await page.locator('[data-propagation-component][data-estimated="true"]').count(), 0);
  assert.equal(await viewport().getAttribute('data-layer'), 'scene');
  assert.equal(requests.length, 0, 'Opening the app must not launch FDS.');
  record('default_soyuz_geometry_has_no_invented_results');

  // Use an in-domain flame so the temporal field can be inspected visually.
  await page.locator('#propagation-incident').selectOption('flaming');
  const input = await readConditions();
  const predictedResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/incidents/predict' && response.request().method() === 'POST',
    { timeout: 125_000 },
  );
  await page.getByRole('button', { name: 'Calculer la carte', exact: true }).click();
  const response = await predictedResponse;
  assert.equal(response.ok(), true, await response.text());
  const predictionRequest = response.request().postDataJSON();
  const assessment = await response.json();
  assert.equal(assessment.model_id, catalog.model.id);
  for (const [key, value] of Object.entries(input)) assert.deepEqual(assessment.config[key], value, key);
  assert.deepEqual(
    assessment.components.map((row) => row.component_id).sort(),
    components.map((row) => row.id).sort(),
  );
  for (const row of assessment.components) {
    assert.equal(row.error, null, `${row.component_id}: ${row.error}`);
    assert.ok(row.result?.frames.length > 1);
    assert.equal(row.result.provenance.model_id, catalog.model.id);
    assert.equal(row.result.provenance.origin, 'prediction');
    await page.locator(`[data-propagation-component="${row.component_id}"][data-estimated="true"]`).waitFor();
  }
  await componentButton(second.id).click();
  assert.equal(await componentButton(second.id).getAttribute('aria-pressed'), 'true');
  const selectedResult = assessment.components.find((row) => row.component_id === second.id).result;
  await ready();
  await assertConsequenceCards(selectedResult);
  await writeFile(path.join(output, 'prediction.json'), JSON.stringify(assessment, null, 2) + '\n');
  record('actual_map_and_second_component_consequences', {
    component_id: second.id,
    config: assessment.config,
    provenance: selectedResult.provenance,
    consequences: selectedResult.summary.consequences,
  });
  await inspectFields(selectedResult, 'prediction');
  for (const [id, label] of [
    ['pov', 'POV équipage'],
    ['top', 'Vue de dessus'],
    ['orbit', 'Vue orbitale'],
  ]) {
    await page.getByRole('button', { name: label, exact: true }).click();
    await page.locator(`.mission-viewport[data-camera="${id}"]`).waitFor();
    await ready();
  }
  await page.getByRole('button', { name: 'Cabine seule', exact: true }).click();
  assert.equal(await viewport().getAttribute('data-layer'), 'scene');
  await page.getByRole('button', { name: 'Fumée thermique', exact: true }).click();
  record('prediction_cameras_and_combined_field');

  const beforeTransfer = await readConditions();
  await page.getByRole('button', { name: 'Simuler ce départ', exact: true }).click();
  await page.locator('[data-propagation-page="simulation"]').waitFor();
  assert.deepEqual(await readConditions(), beforeTransfer);
  assert.equal(requests.length, 0, 'Transfer must preserve conditions without creating a run.');
  assert.equal(await viewport().getAttribute('data-layer'), 'scene');
  record('selected_component_transfers_exactly_without_implicit_fds');

  const launchedResponse = page.waitForResponse(
    (reply) => new URL(reply.url()).pathname === '/api/runs' && reply.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Calculer avec FDS', exact: true }).click();
  const launch = await launchedResponse;
  assert.equal(launch.status(), 202, await launch.text());
  const created = await launch.json();
  createdRunId = created.id;
  assert.equal(requests.length, 1);
  assert.deepEqual(physicalConditions(requests[0]), {
    ...physicalConditions(predictionRequest),
    mode: 'physics',
    component_id: second.id,
  });
  evidence.run_id = createdRunId;
  record('explicit_fds_launch_preserves_every_physical_setting', {
    run_id: createdRunId,
    config: requests[0],
  });
  const terminal = page.locator(`.propagation-job[data-run-id="${createdRunId}"]`).filter({
    has: page.locator('strong', { hasText: /Calcul FDS terminé|Calcul interrompu|Calcul annulé/ }),
  });
  const reporting = setInterval(() => console.log(JSON.stringify({ waiting_for_fds: createdRunId })), 20_000);
  try {
    await terminal.waitFor({ timeout });
  } finally {
    clearInterval(reporting);
  }
  const run = await getJson(`/api/runs/${createdRunId}`);
  assert.equal(run.status, 'completed', run.error ?? run.message);
  completed = true;
  assert.deepEqual(physicalConditions(run.config), physicalConditions(requests[0]));
  assert.equal(run.result.provenance.origin, 'simulation');
  const source = run.result.provenance.incident?.source;
  assert.equal(source?.component_id, second.id);
  assert.deepEqual(source.requested_position_m, second.position_m);
  assert.ok(source.position_m.every(Number.isFinite));
  await page.locator('.mission-viewport[data-field-status="available"]').waitFor();
  await ready();
  await assertConsequenceCards(run.result);
  await writeFile(path.join(output, 'simulation.json'), JSON.stringify(run, null, 2) + '\n');
  record('completed_real_fds_uses_selected_site', {
    run_id: createdRunId,
    provenance: run.result.provenance,
    consequences: run.result.summary.consequences,
  });
  await inspectFields(run.result, 'simulation');
  await setTime(run.result.frames[0].time_s);
  await page.getByRole('button', { name: 'Lire la propagation', exact: true }).click();
  await page.waitForTimeout(1300);
  await pause();
  assert.ok(
    Number(await page.getByLabel('Instant de propagation', { exact: true }).inputValue()) >
      run.result.frames[0].time_s,
  );
  record('simulation_playback_advances_real_recording');

  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Exporter le calcul FDS', exact: true }).click();
  const download = await downloadEvent;
  const zipPath = path.join(output, 'simulation.zip');
  await download.saveAs(zipPath);
  assert.equal((await readFile(zipPath)).subarray(0, 2).toString(), 'PK');
  record('real_simulation_zip_export');

  // Changing conditions hides both the old physical field and the old prediction.
  await page.locator('#propagation-airflow_m_s').fill(String(beforeTransfer.airflow_m_s + 0.01));
  await page.locator('.mission-viewport[data-layer="scene"]').waitFor();
  assert.equal(await page.getByRole('button', { name: 'Température', exact: true }).isDisabled(), true);
  assert.ok((await page.locator('.propagation-job').innerText()).includes('Ses champs sont masqués'));
  await page.getByRole('button', { name: 'Prédiction', exact: true }).click();
  await page.locator('[data-propagation-page="prediction"]').waitFor();
  assert.equal(await page.locator('[data-propagation-component][data-estimated="true"]').count(), 0);
  assert.equal(await viewport().getAttribute('data-layer'), 'scene');
  assert.ok(
    (await page.locator('.propagation-inspector').innerText()).includes('carte précédente est invalidée'),
  );
  record('changed_conditions_hide_both_previous_results');
  await page.locator('#propagation-airflow_m_s').fill(String(beforeTransfer.airflow_m_s));
  await page.locator('[data-propagation-component][data-estimated="true"]').first().waitFor();
  await componentButton(second.id).click();
  await ready();
  await pause();
  await page.setViewportSize({ width: 390, height: 844 });
  await ready();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  await screenshot('prediction-mobile.png');
  await page.getByRole('button', { name: 'Simulation', exact: true }).click();
  await ready();
  await pause();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  await screenshot('simulation-mobile.png');
  assert.equal(requests.length, 1, 'Navigation, playback and changed conditions never relaunch FDS.');
  record('both_pages_mobile_390_without_horizontal_overflow');
  assert.deepEqual(errors, []);
  evidence.passed = true;
} catch (error) {
  evidence.passed = false;
  evidence.failure = error.stack ?? String(error);
  await screenshot('failure.png').catch(() => {});
  process.exitCode = 1;
} finally {
  if (createdRunId && !completed) {
    try {
      const run = await getJson(`/api/runs/${createdRunId}`);
      if (['queued', 'running'].includes(run.status)) {
        const cancel = await page.request.post(`${baseUrl}/api/runs/${createdRunId}/cancel`);
        evidence.cleanup = { run_id: createdRunId, cancellation_requested: cancel.ok() };
      }
    } catch (error) {
      evidence.cleanup = { run_id: createdRunId, error: String(error) };
    }
  }
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
