import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';
import { openTool } from './navigation.mjs';
import * as THREE from 'three';

// Real server, loaded models and GLB only. No fixtures, route mocks or CFD.
const baseUrl = (process.env.IGNIS_BROWSER_URL ?? 'http://127.0.0.1:5173').replace(/\/$/, '');
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
  analyses: [],
  screenshots: [],
  page_errors: errors,
};
const format = (value, decimals = 2) =>
  value.toLocaleString('fr-FR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });

const record = (name, extra = {}) => evidence.checks.push({ name, passed: true, ...extra });
async function screenshot(name) {
  await page.screenshot({ path: path.join(artifacts, name), fullPage: true });
  evidence.screenshots.push(name);
}
async function analyze() {
  const pending = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/prevention/analyze') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Analyser le scénario', exact: true }).click();
  const response = await pending;
  assert.equal(response.ok(), true, await response.text());
  const result = await response.json();
  await page
    .locator('.prevention-map-caption')
    .filter({ hasText: result.id.slice(0, 8) })
    .waitFor();
  evidence.analyses.push(result);
  return result;
}
function expectedState(assessment) {
  if (assessment.status !== 'available' || !assessment.estimate) return 'unknown';
  if (assessment.estimate.phase === 'estimated_ignition_reached') return 'reached';
  return assessment.estimate.within_horizon ? 'within' : 'beyond';
}
async function assertMap(result) {
  for (const assessment of result.components) {
    const item = page.locator(`[data-component-id="${assessment.component_id}"]`);
    assert.equal(await item.getAttribute('data-state'), expectedState(assessment));
    assert.equal(assessment.ignition_probability, null);
  }
}
async function assertSeries(result, assessment) {
  const series = [
    ['observed', assessment.observations.filter((point) => point.time_s <= result.observation_cutoff_s)],
    ['physical', assessment.forecast.filter((point) => point.time_s > result.observation_cutoff_s)],
    ['learned', assessment.learned_forecast.filter((point) => point.time_s > result.observation_cutoff_s)],
  ];
  for (const [name, points] of series) {
    const d = await page.locator(`[data-series="${name}"] path`).getAttribute('d');
    const coordinates = [...d.matchAll(/[ML]([\d.-]+),/g)].map((match) => Number(match[1]));
    assert.equal(
      coordinates.length,
      points.filter((point) => Number.isFinite(point.surface_temperature_c)).length,
    );
    if (points.length) {
      const lastX =
        50 +
        (points.at(-1).time_s /
          Math.max(result.config.duration_s, result.observation_cutoff_s + result.horizon_s, 1)) *
          610;
      assert.ok(
        Math.abs(coordinates.at(-1) - lastX) <= 0.011,
        `${name}: no graphical extrapolation is permitted`,
      );
    }
  }
}

try {
  const catalogResponse = await page.request.get(`${baseUrl}/api/prevention/catalog`);
  assert.equal(catalogResponse.ok(), true, 'The real prevention API must be installed.');
  const catalog = await catalogResponse.json();
  const scenes = (await (await page.request.get(`${baseUrl}/api/scenes`)).json()).scenes;
  const scene = scenes.find((entry) => entry.id === catalog.defaults.scene_id);
  assert.ok(scene);
  assert.ok(catalog.models.length >= 2, 'Both prevention models must be genuinely loaded.');
  const components = catalog.components.filter((entry) => entry.scene_id === scene.id);
  const supported = components.filter((entry) => entry.supported);
  assert.ok(supported.length >= 2);
  const selected = supported[0];
  const battery = components.find((entry) => entry.kind === 'battery');
  assert.ok(battery);

  await page.goto(baseUrl, { waitUntil: 'networkidle' });
  await openTool(page, 'Prévention');
  assert.equal(
    await page
      .getByRole('button', { name: 'Prévention', exact: true, includeHidden: true })
      .getAttribute('aria-current'),
    'page',
  );
  await page.locator('#prevention-scene').waitFor();
  assert.equal(await page.locator('#prevention-scene').inputValue(), catalog.defaults.scene_id);
  await page.locator('.viewport-loading').waitFor({ state: 'hidden' });
  assert.equal(await page.locator('canvas').count(), 1);
  assert.equal(await page.locator('.asset-warning').count(), 0);
  assert.equal(await page.locator('.frame-timestamp').count(), 0);
  for (const entry of components)
    assert.equal(
      await page.locator(`[data-component-id="${entry.id}"]`).getAttribute('data-state'),
      'unknown',
    );
  for (const [key, parameter] of Object.entries(catalog.parameters)) {
    if (key === 'cutoff_s') continue;
    const input = page.locator(`#prevention-${key}`);
    assert.equal(Number(await input.inputValue()), catalog.defaults[key]);
    assert.equal(Number(await input.getAttribute('min')), parameter.min);
    assert.equal(Number(await input.getAttribute('max')), parameter.max);
    assert.equal(Number(await input.getAttribute('step')), parameter.step);
  }
  record('prevention_default_scene_unknown_components_and_catalog_bounds', { scene_id: scene.id });
  await screenshot('ignis-prevention-initial.png');

  // Select a real Three.js marker by projecting its documented physical coordinates.
  const bounds = await page.locator('canvas').boundingBox();
  const aspect = bounds.width / bounds.height;
  const scale = (Math.max(...scene.bounds_m) / 8) * Math.max(1, 1.3 / aspect);
  const camera = new THREE.PerspectiveCamera(38, aspect, 0.05, 150);
  camera.position.set(
    scene.bounds_m[0] / 2 + 8.1 * scale,
    scene.bounds_m[2] / 2 + 6.3 * scale,
    -scene.bounds_m[1] / 2 + 10.8 * scale,
  );
  camera.lookAt(scene.bounds_m[0] / 2, scene.bounds_m[2] * 0.42, -scene.bounds_m[1] / 2);
  camera.updateMatrixWorld();
  const marker = supported[1];
  const point = new THREE.Vector3(marker.position_m[0], marker.position_m[2], -marker.position_m[1]).project(
    camera,
  );
  await page.mouse.click(
    bounds.x + ((point.x + 1) * bounds.width) / 2,
    bounds.y + ((1 - point.y) * bounds.height) / 2,
  );
  await page
    .locator('.prevention-inspector')
    .getByRole('heading', { name: marker.name, exact: true })
    .waitFor();
  record('component_marker_raycast_matches_physical_coordinates', {
    component_id: marker.id,
    position_m: marker.position_m,
  });
  await page.locator(`[data-component-id="${selected.id}"]`).click();

  const initial = await analyze();
  const assessment = initial.components.find((entry) => entry.component_id === selected.id);
  assert.equal(assessment.status, 'available');
  assert.ok(assessment.estimate && Number.isFinite(assessment.estimate.ignition_delay_s));
  assert.equal(assessment.interval, null);
  assert.ok(assessment.learned_forecast.length, 'A genuinely learned thermal forecast is required.');
  await assertMap(initial);
  assert.equal(
    (await page.getByTestId('ignition-delay').textContent()).trim(),
    `${format(assessment.estimate.ignition_delay_s)} s`,
  );
  assert.ok((await page.locator('.prevention-inspector').textContent()).includes('Non quantifiée'));
  await assertSeries(initial, assessment);
  record('real_delay_thermal_models_time_boundary_and_no_extrapolation', { analysis_id: initial.id });

  await page.locator('.prevention-finding').first().waitFor();
  const query = new URLSearchParams({
    component_id: selected.id,
    gravity_g: String(initial.config.gravity_g),
    oxygen_percent: String(initial.config.oxygen_percent),
    airflow_m_s: String(initial.config.airflow_m_s),
    pressure_pa: String(initial.config.pressure_pa),
  });
  const liveFindings = await (await page.request.get(`${baseUrl}/api/prevention/evidence?${query}`)).json();
  const findings = initial.evidence_snapshots_by_component?.[selected.id];
  assert.ok(findings, 'The component-specific evidence must be frozen with its analysis.');
  assert.equal(findings.findings.length, liveFindings.findings.length);
  assert.equal(await page.locator('.prevention-finding').count(), findings.findings.length);
  const sourceCounts = await page.locator('.prevention-source-counts').textContent();
  assert.ok(
    sourceCounts.includes(
      `${findings.findings.filter((finding) => finding.is_nasa_source === true).length} conclusions NASA`,
    ),
  );
  assert.ok(
    sourceCounts.includes(
      `${findings.findings.filter((finding) => finding.is_nasa_source === false).length} conclusions complémentaires hors NASA`,
    ),
  );
  for (let index = 0; index < findings.findings.length; index++) {
    assert.ok(
      (await page.locator('.prevention-finding').nth(index).textContent()).includes(
        findings.findings[index].statement,
      ),
    );
    assert.equal(
      await page
        .locator('.prevention-finding')
        .nth(index)
        .locator('.prevention-source a')
        .getAttribute('href'),
      new URL(findings.findings[index].source.url).href,
    );
  }
  record('ranked_conclusions_sources_and_limits_match_real_catalog', { findings: findings.findings.length });
  await screenshot('ignis-prevention-analysis.png');

  const interpretationResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/prevention/interpret') && response.request().method() === 'POST',
    { timeout: 125_000 },
  );
  await page.getByRole('button', { name: 'Expliquer cette analyse', exact: true }).click();
  const interpreted = await interpretationResponse;
  assert.equal(interpreted.ok(), true, await interpreted.text());
  const interpretation = await interpreted.json();
  if (process.env.IGNIS_EXPECT_PREVENTION_METHOD)
    assert.equal(interpretation.method, process.env.IGNIS_EXPECT_PREVENTION_METHOD);
  await page.locator('.prevention-summary').waitFor();
  assert.equal(await page.locator('.prevention-summary').textContent(), interpretation.summary);
  record('real_interpretation_discloses_actual_method', {
    method: interpretation.method,
    model: interpretation.model,
  });

  await page.getByRole('button', { name: 'Conserver cette analyse comme référence', exact: true }).click();
  const changedCurrent = Math.min(8, catalog.parameters.current_a.max);
  assert.notEqual(changedCurrent, initial.config.current_a);
  await page.locator('#prevention-current_a').fill(String(changedCurrent));
  await page.locator('.prevention-center > .prevention-stale').waitFor();
  assert.equal(
    await page.getByRole('button', { name: 'Expliquer cette analyse', exact: true }).isDisabled(),
    true,
  );
  const changed = await analyze();
  const changedAssessment = changed.components.find((entry) => entry.component_id === selected.id);
  assert.equal(changedAssessment.status, 'available');
  const delta = changedAssessment.estimate.ignition_delay_s - assessment.estimate.ignition_delay_s;
  assert.ok(
    (await page.getByTestId('prevention-comparison').textContent()).includes(
      `${delta > 0 ? '+' : ''}${format(delta)} s`,
    ),
  );
  record('comparison_uses_real_compatible_analyses_and_stale_state', {
    baseline: initial.id,
    current: changed.id,
    delta_s: delta,
  });

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Exporter l’analyse de prévention' }).click();
  const download = await downloadPromise;
  const filename = path.join(artifacts, download.suggestedFilename());
  await download.saveAs(filename);
  const exportedBytes = await readFile(filename);
  assert.equal(exportedBytes.toString('ascii', 0, 2), 'PK');
  for (const entryName of [
    'analysis.json',
    'config.json',
    'thermal_series.csv',
    'evidence_findings.json',
    'README.txt',
  ]) {
    assert.ok(
      exportedBytes.includes(Buffer.from(entryName)),
      `${entryName} must be present in the exported archive`,
    );
  }
  record('real_prevention_zip_download', { filename: download.suggestedFilename() });

  await page.locator('#prevention-airflow_m_s').fill('0.1');
  const outside = await analyze();
  await assertMap(outside);
  const outsideAssessment = outside.components.find((entry) => entry.component_id === selected.id);
  assert.equal(outsideAssessment.status, 'out_of_domain');
  assert.equal(outsideAssessment.estimate, null);
  assert.equal((await page.getByTestId('ignition-delay').textContent()).trim(), '— s');
  assert.ok((await page.getByTestId('prevention-comparison').textContent()).includes('Écart non calculé'));
  record('forced_airflow_has_no_ignition_estimate_or_comparison_delta');
  await page.locator(`[data-component-id="${battery.id}"]`).click();
  assert.equal(
    await page.locator('.prevention-inspector [data-prevention-state]').getAttribute('data-prevention-state'),
    'unknown',
  );
  assert.equal(await page.locator('.prevention-chart svg[role="img"]').count(), 0);
  await page.locator('.prevention-finding').first().waitFor();
  const batteryFindings = outside.evidence_snapshots_by_component?.[battery.id];
  assert.ok(batteryFindings, 'The battery needs its own frozen applicability assessment.');
  const batteryEvidence = await page.locator('.prevention-finding').first().textContent();
  assert.ok(batteryFindings.findings[0].reasons.every((reason) => batteryEvidence.includes(reason)));
  record('unsupported_battery_stays_unknown_without_fabricated_series');

  await page.getByRole('button', { name: 'Relecture simulée', exact: true }).click();
  await page.locator('#prevention-observation_cutoff_s').fill(String(initial.config.duration_s));
  assert.equal(
    await page.getByRole('button', { name: 'Analyser le scénario', exact: true }).isDisabled(),
    true,
  );
  await page.locator('#prevention-observation_cutoff_s').fill(String(initial.config.observation_cutoff_s));
  await page.locator('#prevention-airflow_m_s').fill('0');
  await page.locator(`[data-component-id="${selected.id}"]`).click();
  record('replay_rejects_observation_plus_horizon_beyond_duration');
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  await screenshot('ignis-prevention-mobile.png');
  record('mobile_prevention_has_no_horizontal_overflow');

  await page.setViewportSize({ width: 1600, height: 1150 });
  await openTool(page, 'Laboratoire');
  await page.locator('#scene-select').waitFor();
  await openTool(page, 'Prévention');
  await page.locator('#prevention-scene').waitFor();
  assert.equal(await page.locator('.frame-timestamp').count(), 0);
  assert.ok((await page.locator('.prevention-map-caption').textContent()).includes(outside.id.slice(0, 8)));
  assert.equal(await page.locator('.prevention-comparison').count(), 1);
  record('laboratory_navigation_does_not_restore_fire_in_prevention');
  assert.deepEqual(errors, []);
  evidence.passed = true;
} catch (error) {
  evidence.passed = false;
  evidence.failure = error.stack ?? String(error);
  await screenshot('ignis-prevention-failure.png').catch(() => {});
  throw error;
} finally {
  await writeFile(path.join(artifacts, 'prevention-verification.json'), JSON.stringify(evidence, null, 2));
  await browser.close();
}
