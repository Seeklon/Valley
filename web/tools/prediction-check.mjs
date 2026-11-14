import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

// Real preloaded models only. No network mocks, CFD or language-model request.
const baseUrl = (process.env.IGNIS_BROWSER_URL ?? 'http://127.0.0.1:5173').replace(/\/$/, '');
const sceneId = process.env.IGNIS_BROWSER_SCENE ?? 'soyuz';
const artifacts = path.resolve('artifacts');
await mkdir(artifacts, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.IGNIS_BROWSER_PATH || undefined,
  args:
    process.platform === 'linux'
      ? ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']
      : [],
});
const context = await browser.newContext({ viewport: { width: 1600, height: 1150 }, deviceScaleFactor: 1 });
const page = await context.newPage();
page.setDefaultTimeout(60_000);
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));
const evidence = {
  checked_at: new Date().toISOString(),
  base_url: baseUrl,
  scene_id: sceneId,
  checks: [],
  runs: [],
  screenshots: [],
  page_errors: errors,
};
const french = (value, decimals = 2) =>
  value.toLocaleString('fr-FR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });

async function setRange(locator, value) {
  await locator.evaluate((element, next) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(element, String(next));
    element.dispatchEvent(new Event('input', { bubbles: true }));
    element.dispatchEvent(new Event('change', { bubbles: true }));
  }, value);
}

async function launchModel(model) {
  await page.locator('.model-picker select').selectOption(model.id);
  const createdResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/runs') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Lancer la prédiction', exact: true }).click();
  const response = await createdResponse;
  assert.equal(response.status(), 202, await response.text());
  const created = await response.json();
  await page
    .locator('.execution-panel .job-status.completed')
    .filter({ hasText: created.id.slice(0, 8) })
    .waitFor();
  const resultResponse = await page.request.get(`${baseUrl}/api/runs/${created.id}`);
  assert.equal(resultResponse.ok(), true);
  const run = await resultResponse.json();
  assert.equal(run.status, 'completed');
  assert.equal(run.config.scene_id, sceneId);
  assert.equal(run.config.mode, 'prediction');
  assert.equal(run.result.provenance.model_id, model.id);
  assert.ok(run.result.metrics.length > 1);
  assert.ok(run.result.metrics.some((row) => Number.isFinite(row.temperature_max_c)));
  evidence.runs.push({
    id: run.id,
    model_id: model.id,
    config: run.config,
    metrics: run.result.metrics.length,
    frames: run.result.frames.length,
    provenance: run.result.provenance,
  });
  return run;
}

try {
  const healthResponse = await page.request.get(`${baseUrl}/api/health`);
  assert.equal(healthResponse.ok(), true);
  const health = await healthResponse.json();
  assert.equal(health.capabilities.prediction, true);
  const modelsResponse = await page.request.get(`${baseUrl}/api/models`);
  const models = (await modelsResponse.json()).models;
  const spatial = models.find((model) => model.loaded === true && model.kind === 'spatial_mlp');
  const scalar = models.find((model) => model.loaded === true && model.kind === 'scalar_forest');
  assert.ok(spatial && scalar, 'Both actually loaded models are required.');
  evidence.runtime = health;

  await page.goto(baseUrl, { waitUntil: 'networkidle' });
  await page.locator('#scene-select').selectOption(sceneId);
  await page.locator('.viewport-loading').waitFor({ state: 'hidden' });
  assert.equal(await page.locator('.asset-warning').count(), 0);
  await page.getByRole('button', { name: 'Prédiction', exact: true }).click();
  await page.getByRole('spinbutton', { name: /Source active/ }).fill('15');
  await page.getByRole('spinbutton', { name: /^Simulation/ }).fill('30');
  await setRange(page.getByRole('slider', { name: 'Oxygène', exact: true }), 21);
  await setRange(page.getByRole('slider', { name: 'Vitesse d’entrée', exact: true }), 0.2);
  await setRange(page.getByRole('slider', { name: 'Puissance du feu imposée', exact: true }), 1000);
  const spatialRun = await launchModel(spatial);
  await page
    .locator('.execution-panel .model-consistency-note')
    .getByText('Prévisualisation exploratoire', { exact: true })
    .waitFor();
  assert.ok(spatialRun.result.frames.length > 1);
  await page.getByRole('button', { name: 'Suspendre la lecture', exact: true }).click();
  const peakFrame = spatialRun.result.frames.reduce(
    (best, frame) => {
      const peak = Math.max(...(frame.temperature_c ?? []).filter(Number.isFinite));
      return peak > best.peak ? { peak, time: frame.time_s } : best;
    },
    { peak: -Infinity, time: 0 },
  );
  await setRange(page.getByRole('slider', { name: 'Instant de visualisation' }), peakFrame.time);
  await page.getByRole('button', { name: 'Température', exact: true }).click();
  assert.ok((await page.locator('.metric-number').first().textContent()).includes('°C'));
  assert.equal(
    await page.locator('.timeline-caption').textContent(),
    `${spatialRun.result.frames.length} frames`,
  );
  evidence.checks.push({
    name: 'real_spatial_prediction_autoplay_timeline_and_field',
    passed: true,
    peak_frame_time_s: peakFrame.time,
  });
  await page.screenshot({ path: path.join(artifacts, 'ignis-prediction-spatial.png'), fullPage: true });
  evidence.screenshots.push('ignis-prediction-spatial.png');
  await page.getByRole('button', { name: 'Définir comme référence' }).click();

  await page.locator('.model-picker select').selectOption(scalar.id);
  await page.locator('.result-context').filter({ hasText: 'Les paramètres ont changé' }).waitFor();
  await setRange(page.getByRole('slider', { name: 'Vitesse d’entrée', exact: true }), 0.3);
  const scalarRun = await launchModel(scalar);
  assert.equal(scalarRun.result.frames.length, 0);
  assert.equal(await page.locator('.timeline-caption').textContent(), 'Métriques uniquement');
  assert.equal(await page.getByRole('button', { name: 'Température', exact: true }).isDisabled(), true);
  assert.equal(await page.locator('.baseline-card').count(), 1);
  assert.equal(await page.locator('.chart-plot path[stroke-dasharray]').count(), 1);
  const lastMetric = scalarRun.result.metrics.at(-1);
  assert.ok(
    (await page.locator('.metric-number').first().textContent()).includes(
      french(lastMetric.temperature_max_c, 1),
    ),
  );
  evidence.checks.push({ name: 'real_scalar_prediction_no_fabricated_fields_and_comparison', passed: true });
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Exporter cet essai' }).click();
  const download = await downloadPromise;
  const exportedPath = path.join(artifacts, download.suggestedFilename());
  await download.saveAs(exportedPath);
  assert.equal((await readFile(exportedPath)).toString('ascii', 0, 2), 'PK');
  evidence.checks.push({
    name: 'real_run_export_via_download_link',
    passed: true,
    filename: download.suggestedFilename(),
  });
  await page.screenshot({ path: path.join(artifacts, 'ignis-prediction-comparison.png'), fullPage: true });
  evidence.screenshots.push('ignis-prediction-comparison.png');

  await setRange(page.getByRole('slider', { name: 'Puissance du feu imposée', exact: true }), 100);
  await page.locator('.domain-warnings').waitFor();
  assert.equal(
    await page.getByRole('button', { name: 'Lancer la prédiction', exact: true }).isDisabled(),
    true,
  );
  const rejected = await page.request.post(`${baseUrl}/api/runs`, {
    data: { ...scalarRun.config, ignition_power_w: 100 },
  });
  assert.equal(rejected.status(), 422);
  evidence.checks.push({ name: 'domain_rejection_in_browser_and_real_api', passed: true });

  await page.reload({ waitUntil: 'networkidle' });
  await page
    .locator('.execution-panel .job-status.completed')
    .filter({ hasText: scalarRun.id.slice(0, 8) })
    .waitFor();
  evidence.checks.push({ name: 'last_real_run_restored_after_reload', passed: true });
  await page.getByRole('button', { name: 'Modèles', exact: true }).click();
  assert.equal(await page.locator('.model-card').count(), models.length);
  for (const model of [spatial, scalar]) {
    const card = page
      .locator('.model-card')
      .filter({ has: page.getByRole('heading', { name: model.name, exact: true }) });
    const row = card
      .locator('.model-evaluation-table')
      .first()
      .getByRole('row')
      .filter({ has: page.getByRole('rowheader', { name: 'Température maximale · MAE', exact: true }) });
    assert.ok(
      (await row.locator('td').nth(0).textContent()).includes(
        french(model.metrics.validation.metric_errors.temperature_max_c.mae),
      ),
    );
    assert.ok(
      (await row.locator('td').nth(1).textContent()).includes(
        french(model.metrics.test.metric_errors.temperature_max_c.mae),
      ),
    );
    const soyuzRows = card.locator('.model-coverage-note tbody tr');
    assert.equal(await soyuzRows.count(), 2);
    assert.equal((await soyuzRows.nth(0).locator('td').first().textContent()).trim(), '2');
    assert.equal((await soyuzRows.nth(1).locator('td').first().textContent()).trim(), '2');
    assert.equal(
      await card.locator('.model-domain').getByText('0,05 à 0,40 m/s', { exact: true }).count(),
      1,
    );
    if (model.kind === 'spatial_mlp') {
      const consistencyNote = card.locator('.model-consistency-note');
      await consistencyNote.getByText('Prévisualisation exploratoire', { exact: true }).waitFor();
      if (model.metrics.test.consistency) {
        const text = await consistencyNote.locator('.consistency-observations').textContent();
        assert.ok(text.includes(french(model.metrics.test.consistency.mean_above_global_max_frames, 0)));
        assert.ok(text.includes(french(model.metrics.test.consistency.sample_above_global_max_frames, 0)));
      }
    }
  }
  evidence.checks.push({
    name: 'model_evaluation_tables_match_real_metadata_and_show_soyuz_limits',
    passed: true,
  });
  await page.screenshot({ path: path.join(artifacts, 'ignis-models-evaluation.png'), fullPage: true });
  evidence.screenshots.push('ignis-models-evaluation.png');
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(artifacts, 'ignis-models-mobile.png'), fullPage: true });
  evidence.screenshots.push('ignis-models-mobile.png');
  evidence.checks.push({ name: 'mobile_model_evaluation_without_horizontal_overflow', passed: true });
  assert.deepEqual(errors, []);
  evidence.passed = true;
} catch (error) {
  evidence.passed = false;
  evidence.failure = error instanceof Error ? error.stack : String(error);
  await page
    .screenshot({ path: path.join(artifacts, 'prediction-failure.png'), fullPage: true })
    .catch(() => {});
  process.exitCode = 1;
} finally {
  await writeFile(
    path.join(artifacts, 'prediction-verification.json'),
    `${JSON.stringify(evidence, null, 2)}\n`,
  );
  console.log(
    JSON.stringify(
      {
        passed: evidence.passed,
        checks: evidence.checks,
        runs: evidence.runs.map(({ id, model_id, frames, metrics }) => ({ id, model_id, frames, metrics })),
        page_errors: errors,
        failure: evidence.failure,
        report: path.join(artifacts, 'prediction-verification.json'),
      },
      null,
      2,
    ),
  );
  await browser.close();
}
