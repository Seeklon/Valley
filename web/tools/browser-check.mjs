import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

// This check uses the real API and GLB assets. It never installs route mocks.
const baseUrl = process.env.IGNIS_BROWSER_URL ?? 'http://127.0.0.1:5173';
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
  checks: [],
  screenshots: [],
  page_errors: errors,
};

try {
  const healthResponse = await page.request.get(`${baseUrl}/api/health`);
  assert.equal(healthResponse.ok(), true, 'The real API must be available.');
  const health = await healthResponse.json();
  const catalog = await (await page.request.get(`${baseUrl}/api/scenes`)).json();
  evidence.runtime = health;
  assert.ok(catalog.scenes.length > 0, 'A real scene catalogue is required.');
  await page.goto(baseUrl, { waitUntil: 'networkidle' });
  await page.locator('#scene-select').selectOption(catalog.scenes[0].id);
  await page.locator('.viewport-loading').waitFor({ state: 'hidden' });
  assert.equal(await page.locator('canvas').count(), 1);
  assert.equal(await page.locator('.asset-warning').count(), 0, 'The initial scene must load the real GLB.');
  evidence.checks.push({ name: 'initial_scene_real_glb', passed: true, scene_id: catalog.scenes[0].id });
  const initialAsset = await page.request.get(`${baseUrl}${catalog.scenes[0].asset_url}`);
  assert.equal(initialAsset.ok(), true);
  assert.equal((await initialAsset.body()).toString('ascii', 0, 4), 'glTF');

  // A disconnected solver must never display fabricated measurements or an enabled launch button.
  if (!health.capabilities.physics) {
    assert.equal(
      await page.getByRole('button', { name: 'Lancer la simulation', exact: true }).isDisabled(),
      true,
    );
    assert.equal(await page.locator('.metric-number').first().innerText(), '—°C');
    evidence.checks.push({ name: 'unavailable_solver_has_no_fake_results', passed: true });
  }

  const fuel = catalog.scenes[0].objects.find((object) => object.role === 'fuel');
  if (fuel) {
    await page.locator('#object-select').selectOption(fuel.id);
    await page.getByRole('heading', { name: fuel.name, exact: true }).waitFor();
    evidence.checks.push({ name: 'semantic_object_inspector', passed: true, object_id: fuel.id });
    await page.getByRole('button', { name: 'Désélectionner l’objet' }).click();
  }
  await page.screenshot({ path: path.join(artifacts, 'ignis-cockpit-desktop.png'), fullPage: true });
  evidence.screenshots.push('ignis-cockpit-desktop.png');

  const assetChecks = [];
  for (const scene of catalog.scenes) {
    const response = await page.request.head(`${baseUrl}${scene.asset_url}`);
    if (!response.ok()) {
      assetChecks.push({ scene_id: scene.id, available: false, status: response.status() });
      continue;
    }
    await page.locator('#scene-select').selectOption(scene.id);
    await page.locator('.viewport-loading').waitFor({ state: 'hidden' });
    assert.equal(await page.locator('.asset-warning').count(), 0, `GLB loading failed for ${scene.id}`);
    assetChecks.push({ scene_id: scene.id, available: true, rendered: true });
    if (scene.id === 'soyuz') {
      await page.screenshot({ path: path.join(artifacts, 'ignis-soyuz-desktop.png'), fullPage: true });
      evidence.screenshots.push('ignis-soyuz-desktop.png');
    }
  }
  evidence.scenes = assetChecks;

  if (health.capabilities.insights) {
    const responsePromise = page.waitForResponse(
      (response) => response.url().endsWith('/api/insights') && response.request().method() === 'POST',
      { timeout: 125_000 },
    );
    await page.getByRole('button', { name: 'Interpréter ce scénario' }).click();
    const response = await responsePromise;
    assert.equal(response.ok(), true, 'The real NASA interpretation endpoint must respond.');
    const insight = await response.json();
    if (process.env.IGNIS_EXPECT_INSIGHT_METHOD)
      assert.equal(insight.method, process.env.IGNIS_EXPECT_INSIGHT_METHOD);
    await page.locator('.insights-summary').waitFor();
    assert.equal(await page.locator('.insights-summary').textContent(), insight.summary);
    assert.equal(await page.locator('.ranked-sources article').count(), insight.sources.length);
    if (insight.method === 'codex_grounded_in_nasa_evidence') {
      assert.ok((await page.locator('.insights-method').textContent()).includes('Codex'));
      assert.ok((await page.locator('.insights-method').textContent()).includes(insight.model));
    }
    evidence.checks.push({
      name: 'nasa_interpretation_uses_actual_response_and_sources',
      passed: true,
      method: insight.method,
      model: insight.model,
      sources: insight.sources.length,
    });
    await page.screenshot({ path: path.join(artifacts, 'ignis-interpretation-desktop.png'), fullPage: true });
    evidence.screenshots.push('ignis-interpretation-desktop.png');
  }

  await page.getByRole('button', { name: 'Modèles', exact: true }).click();
  const models = await (await page.request.get(`${baseUrl}/api/models`)).json();
  assert.equal(await page.locator('.model-card').count(), models.models.length);
  evidence.checks.push({
    name: 'model_registry_matches_real_api',
    passed: true,
    models: models.models.length,
  });
  for (const model of models.models.filter((item) => item.kind === 'spatial_mlp')) {
    const card = page.locator('.model-card').filter({
      has: page.getByRole('heading', { name: model.name, exact: true }),
    });
    await card.getByText('Prévisualisation exploratoire', { exact: true }).waitFor();
    if (model.metrics?.test?.consistency) {
      const audit = model.metrics.test.consistency;
      const text = await card.locator('.consistency-observations').textContent();
      assert.ok(text.includes(audit.mean_above_global_max_frames.toLocaleString('fr-FR')));
      assert.ok(text.includes(audit.sample_above_global_max_frames.toLocaleString('fr-FR')));
      evidence.checks.push({
        name: 'spatial_model_consistency_limits_match_real_audit',
        passed: true,
        model_id: model.id,
        audit,
      });
    }
  }
  await page.screenshot({ path: path.join(artifacts, 'ignis-models-final.png'), fullPage: true });
  evidence.screenshots.push('ignis-models-final.png');
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  await page.screenshot({ path: path.join(artifacts, 'ignis-models-final-mobile.png'), fullPage: true });
  evidence.screenshots.push('ignis-models-final-mobile.png');
  await page.setViewportSize({ width: 1600, height: 1150 });

  await page.getByRole('button', { name: 'Sources NASA', exact: true }).click();
  const sources = await (await page.request.get(`${baseUrl}/api/sources`)).json();
  assert.equal(await page.locator('.source-card').count(), sources.sources.length);
  const firstObservations = page
    .locator('.source-card')
    .first()
    .getByText(/Explorer les observations importées/);
  if (await firstObservations.count()) {
    await firstObservations.click();
    await page
      .getByRole('textbox', { name: 'Filtrer les observations par matériau ou identifiant' })
      .first()
      .fill('PMMA');
    const visibleRows = await page.locator('.source-card').first().locator('tbody tr').allTextContents();
    assert.ok(visibleRows.length > 0);
    assert.ok(visibleRows.every((row) => row.toLowerCase().includes('pmma')));
    evidence.checks.push({
      name: 'nasa_observations_filtered_from_real_table',
      passed: true,
      visible_rows: visibleRows.length,
    });
  }
  await page.screenshot({ path: path.join(artifacts, 'ignis-sources-desktop.png'), fullPage: true });
  evidence.screenshots.push('ignis-sources-desktop.png');

  await page.getByRole('button', { name: 'Scènes', exact: true }).click();
  assert.equal(await page.locator('.scene-card').count(), catalog.scenes.length);
  await page.getByRole('button', { name: 'Ouvrir le laboratoire' }).first().click();
  await page.locator('.viewport-loading').waitFor({ state: 'hidden' });
  await page.getByText('Générer une campagne de scènes', { exact: true }).click();
  assert.equal(await page.locator('.campaign-scene-list input').count(), catalog.scenes.length);
  if (!health.capabilities.campaigns)
    assert.equal(await page.getByRole('button', { name: 'Générer 12 essais' }).isDisabled(), true);
  evidence.checks.push({ name: 'campaign_capabilities_and_scene_selection', passed: true });
  await page.getByText('Générer une campagne de scènes', { exact: true }).click();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('canvas').waitFor();
  await page.screenshot({ path: path.join(artifacts, 'ignis-cockpit-mobile.png'), fullPage: true });
  assert.equal(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    true,
    'Mobile view must not scroll horizontally.',
  );
  await page.getByRole('button', { name: 'Paramètres', exact: true }).click();
  assert.equal(await page.getByLabel('Environnement', { exact: true }).isVisible(), true);
  evidence.checks.push({
    name: 'mobile_navigation_parameters_no_overflow',
    passed: true,
    viewport: [390, 844],
  });
  evidence.screenshots.push('ignis-cockpit-mobile.png');
  assert.deepEqual(errors, []);
  evidence.passed = true;
} catch (error) {
  evidence.passed = false;
  evidence.failure = error instanceof Error ? error.message : String(error);
  await page
    .screenshot({ path: path.join(artifacts, 'browser-failure.png'), fullPage: true })
    .catch(() => {});
  process.exitCode = 1;
} finally {
  await writeFile(
    path.join(artifacts, 'browser-verification.json'),
    `${JSON.stringify(evidence, null, 2)}\n`,
  );
  console.log(JSON.stringify(evidence, null, 2));
  await browser.close();
}
