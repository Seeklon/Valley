import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

// Uses real exported predictions only; never intercepts requests or submits compute.
const base = (process.env.IGNIS_BROWSER_URL ?? 'http://127.0.0.1:5177').replace(/\/$/, '');
const route = process.env.IGNIS_ISS_ROUTE ?? '#iss';
const ventilationOnly = process.env.IGNIS_ISS_VENT_ONLY === '1';
const output = path.resolve(process.env.IGNIS_ISS_EVIDENCE ?? 'artifacts/iss-poc');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.IGNIS_BROWSER_PATH || undefined,
  args:
    process.platform === 'linux'
      ? ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']
      : [],
});
const page = await browser.newPage({ viewport: { width: 1550, height: 1050 }, deviceScaleFactor: 1 });
page.setDefaultTimeout(60_000);
const errors = [],
  writes = [],
  checks = [],
  screenshots = [];
page.on('pageerror', (error) => errors.push(error.message));
page.on('request', (request) => {
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method()))
    writes.push({ method: request.method(), url: request.url() });
});
const root = () => page.locator('[data-iss-poc]');
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');
const record = (name, evidence = {}) => {
  checks.push({ name, passed: true, ...evidence });
  console.log(JSON.stringify({ check: name, passed: true }));
};
const caseUrl = (url) => (url.startsWith('/') ? url : '/poc/iss/' + url.replace(/^\.\//, ''));
async function json(url) {
  const response = await page.request.get(base + url);
  assert.ok(response.ok(), `${url}: ${response.status()}`);
  return response.json();
}
async function replay(entry) {
  const response = await page.request.get(base + caseUrl(entry.url));
  assert.ok(response.ok());
  const bytes = await response.body();
  assert.equal(hash(bytes), entry.sha256, 'Replay bytes must match the frozen index.');
  const data = JSON.parse(bytes.toString('utf8'));
  assert.equal(data.id, entry.id);
  assert.equal(data.layout_id, entry.layout_id);
  assert.equal(data.module_id, entry.module_id);
  return data;
}
async function ready(id) {
  await page.waitForFunction((expected) => {
    const el = document.querySelector('[data-iss-poc]');
    return el?.getAttribute('data-case-id') === expected && el.getAttribute('data-time-s') !== '';
  }, id);
  await root().locator('canvas').waitFor();
  await page.waitForTimeout(300);
  assert.equal(await root().locator('.iss-error').count(), 0);
}
async function select(entry) {
  await root().locator(`[data-iss-module="${entry.module_id}"]`).click();
  await root().getByLabel('Partition ISS', { exact: true }).selectOption(entry.split);
  await root().getByLabel('Scénario ISS', { exact: true }).selectOption(entry.id);
  await ready(entry.id);
}
async function frame(index, time) {
  await root()
    .getByLabel('Instant ISS', { exact: true })
    .evaluate((input, value) => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, String(value));
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }, index);
  await page.waitForFunction(
    (expected) => Number(document.querySelector('[data-iss-poc]')?.getAttribute('data-time-s')) === expected,
    time,
  );
  await page.waitForTimeout(250);
}
async function capture(name) {
  await page.screenshot({ path: path.join(output, name), fullPage: true });
  screenshots.push(name);
}
function presentationFrame(data) {
  let peak = 0,
    temperature = -Infinity,
    smoky = 0,
    soot = 0;
  data.frames.forEach((item, i) =>
    item.temperature_c.forEach((value, p) => {
      if (item.heat_valid_mask[p] && value !== null && value > temperature) {
        temperature = value;
        peak = i;
      }
      const smoke = item.soot_kg_m3[p];
      if (item.smoke_valid_mask[p] && smoke !== null && smoke > soot) {
        soot = smoke;
        smoky = i;
      }
    }),
  );
  return temperature >= data.conditions.ambient_temperature_c + data.heat_delta_c
    ? peak
    : soot >= data.smoke_threshold_kg_m3
      ? smoky
      : peak;
}
async function cameraValues(key) {
  return (await root().locator('canvas').getAttribute(key)).split(',').map(Number);
}
let index;
try {
  index = await json('/poc/iss/index.json');
  assert.equal(index.schema_version, 'iss-poc-1');
  assert.match(index.model.weights_sha256, /^[a-f0-9]{64}$/);
  assert.match(index.model.dataset_sha256, /^[a-f0-9]{64}$/);
  assert.ok(index.cases.length > 0);
  await page.goto(`${base}/${route}`, { waitUntil: 'networkidle' });
  await root().waitFor();
  const initial =
    index.cases.find((item) => item.id === index.default_case_id) ??
    index.cases.find((item) => item.split === 'validation') ??
    index.cases[0];
  await ready(initial.id);
  assert.ok((await root().innerText()).includes('Inférence enregistrée'));
  assert.ok((await root().innerText()).includes('probabilité de départ de feu'));
  record('recorded_export_with_heat_smoke_and_provenance', {
    cases: index.cases.length,
    model: index.model.id,
  });

  if (!ventilationOnly) {
    for (const module of [...new Set(index.cases.map((item) => item.module_id))]) {
      const selected =
        index.cases.find((item) => item.id === index.example_cases?.modules?.[module]) ??
        index.cases.find((item) => item.module_id === module && item.split === 'validation') ??
        index.cases.find((item) => item.module_id === module);
      await select(selected);
      const moduleData = await replay(selected);
      const modulePeak = presentationFrame(moduleData);
      await frame(modulePeak, moduleData.frames[modulePeak].time_s);
      const source = await cameraValues('data-source-ndc');
      assert.ok(
        Math.abs(source[0]) < 0.6 && Math.abs(source[1]) < 0.6 && source[2] > -1 && source[2] < 1,
        'Conditional source must start inside the central view.',
      );
      await capture(`iss-${module}.png`);
      const render = {
        calls: Number(await root().locator('canvas').getAttribute('data-draw-calls')),
        triangles: Number(await root().locator('canvas').getAttribute('data-triangles')),
      };
      assert.ok(render.calls > 0 && render.triangles > 0);
      await root().getByRole('button', { name: 'Ensemble', exact: true }).click();
      await page.waitForTimeout(300);
      await capture(`iss-${module}-overview.png`);
      await root().getByRole('button', { name: 'Intérieur', exact: true }).click();
      await root().getByLabel('Couche chaleur', { exact: true }).uncheck();
      await page.waitForTimeout(300);
      await capture(`iss-${module}-smoke.png`);
      await root().getByLabel('Couche chaleur', { exact: true }).check();
      const moduleTest = index.cases.find((item) => item.module_id === module && item.split === 'test');
      assert.ok(moduleTest, `${module} must provide a held-out layout.`);
      await select(moduleTest);
      await replay(moduleTest);
      await capture(`iss-${module}-test.png`);
      record('module_matches_its_own_geometry_and_replay', {
        module,
        id: selected.id,
        layout: selected.layout_id,
        source_ndc: source,
        test_id: moduleTest.id,
        rendered: render,
      });
    }

    for (const [example, file] of [
      ['cold_control', 'iss-cold-control.png'],
      ['failure', 'iss-model-failure.png'],
    ]) {
      const selected = index.cases.find((item) => item.id === index.example_cases?.[example]);
      assert.ok(selected, `${example} example is required.`);
      await select(selected);
      const data = await replay(selected);
      const peak = presentationFrame(data);
      await frame(peak, data.frames[peak].time_s);
      if (example === 'cold_control') {
        assert.equal(data.conditions.power_w, 0);
        for (const channel of ['heat', 'smoke'])
          assert.equal(selected.metrics[channel].tp + selected.metrics[channel].fn, 0);
      }
      await root().getByRole('button', { name: 'Erreurs', exact: true }).click();
      await capture(file);
      record(`honest_${example}_accessible`, {
        id: selected.id,
        metrics: selected.metrics,
        time_s: data.frames[peak].time_s,
      });
      await root().getByRole('button', { name: 'Prédiction ML', exact: true }).click();
    }
    const heldout = index.cases.find((item) => item.split === 'test');
    assert.ok(heldout);
    await select(heldout);
    await replay(heldout);
    assert.equal(await root().getByLabel('Partition ISS', { exact: true }).inputValue(), 'test');
    await capture('iss-heldout-test.png');
    record('heldout_partition_accessible', { id: heldout.id, layout_id: heldout.layout_id });
  }

  const ventilationCase = index.cases.find(
    (entry) => entry.split === 'train' && entry.ventilation_group_id && entry.ventilation_state === 'still',
  );
  if (ventilationCase) {
    const states = ['still', 'slow', 'fast', 'reverse'];
    const quartet = states.map((state) =>
      index.cases.find(
        (entry) =>
          entry.ventilation_group_id === ventilationCase.ventilation_group_id &&
          entry.split === ventilationCase.split &&
          entry.module_id === ventilationCase.module_id &&
          entry.layout_id === ventilationCase.layout_id &&
          entry.ventilation_state === state,
      ),
    );
    assert.ok(quartet.every(Boolean), 'Ventilation controls require a complete quartet.');
    await select(ventilationCase);
    assert.equal(await root().locator('[data-iss-ventilation]').count(), 4);
    const replays = await Promise.all(quartet.map(replay));
    const still = replays[0];
    const differingTime = still.frames.findLastIndex(
      (observed) =>
        observed.time_s > 0 &&
        replays.some((data) => !data.frames.some((other) => other.time_s === observed.time_s)),
    );
    const startFrame = differingTime >= 0 ? differingTime : Math.floor(still.frames.length / 2);
    const targetTime = still.frames[startFrame].time_s;
    await frame(startFrame, targetTime);
    const canvas = root().locator('canvas');
    await canvas.scrollIntoViewIfNeeded();
    const before = await cameraValues('data-camera-direction');
    const box = await canvas.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 45, box.y + box.height / 2 - 15, { steps: 5 });
    await page.mouse.up();
    await page.waitForFunction((direction) => {
      const next = document.querySelector('[data-iss-poc] canvas')?.getAttribute('data-camera-direction');
      return next?.split(',').some((n, i) => Number(n) !== direction[i]);
    }, before);
    const position = await cameraValues('data-camera-position');
    const direction = await cameraValues('data-camera-direction');
    const observations = [];
    for (const entry of [...quartet.slice(1), quartet[0], quartet[2]]) {
      if (entry === quartet[2] && observations.length === 4)
        await root().getByLabel('Scénario ISS', { exact: true }).selectOption(entry.id);
      else await root().locator(`[data-iss-ventilation="${entry.ventilation_state}"]`).click();
      await ready(entry.id);
      const replayData = replays[quartet.indexOf(entry)];
      const nearest = replayData.frames.reduce((closest, observed) =>
        Math.abs(observed.time_s - targetTime) < Math.abs(closest.time_s - targetTime) ? observed : closest,
      );
      assert.equal(Number(await root().getAttribute('data-time-s')), nearest.time_s);
      assert.equal(Number(await root().getAttribute('data-comparison-time-s')), targetTime);
      assert.equal(await root().getAttribute('data-ventilation-group'), ventilationCase.ventilation_group_id);
      for (const [key, expected] of [
        ['data-camera-position', position],
        ['data-camera-direction', direction],
      ]) {
        const actual = await cameraValues(key);
        assert.ok(
          actual.every((n, i) => Math.abs(n - expected[i]) <= 0.000002),
          `${key} must survive the state switch.`,
        );
      }
      observations.push({ id: entry.id, state: entry.ventilation_state, time_s: nearest.time_s });
    }
    await capture('iss-ventilation-comparison.png');
    await root().getByRole('button', { name: 'Ensemble', exact: true }).click();
    await page.waitForFunction((oldPosition) => {
      const value = document.querySelector('[data-iss-poc] canvas')?.getAttribute('data-camera-position');
      return value?.split(',').some((n, i) => Math.abs(Number(n) - oldPosition[i]) > 0.1);
    }, position);
    const overviewDefault = await cameraValues('data-camera-position');
    const overviewBox = await canvas.boundingBox();
    await page.mouse.move(overviewBox.x + overviewBox.width / 2, overviewBox.y + overviewBox.height / 2);
    await page.mouse.wheel(0, -220);
    await page.waitForFunction((oldPosition) => {
      const value = document.querySelector('[data-iss-poc] canvas')?.getAttribute('data-camera-position');
      return value?.split(',').some((n, i) => Math.abs(Number(n) - oldPosition[i]) > 0.01);
    }, overviewDefault);
    const overviewPosition = await cameraValues('data-camera-position');
    const overviewDirection = await cameraValues('data-camera-direction');
    await root().locator('[data-iss-ventilation="reverse"]').click();
    await ready(quartet[3].id);
    for (const [key, expected] of [
      ['data-camera-position', overviewPosition],
      ['data-camera-direction', overviewDirection],
    ]) {
      const actual = await cameraValues(key);
      assert.ok(
        actual.every((n, i) => Math.abs(n - expected[i]) <= 0.000002),
        `${key} must survive in overview.`,
      );
    }
    await capture('iss-ventilation-overview.png');
    await root().getByRole('button', { name: 'Recentrer la caméra', exact: true }).click();
    await page.waitForFunction((zoomed) => {
      const value = document.querySelector('[data-iss-poc] canvas')?.getAttribute('data-camera-position');
      return value?.split(',').some((n, i) => Math.abs(Number(n) - zoomed[i]) > 0.01);
    }, overviewPosition);
    await root().getByRole('button', { name: 'Intérieur', exact: true }).click();
    const other = index.cases.find(
      (entry) =>
        entry.split === ventilationCase.split &&
        entry.module_id === ventilationCase.module_id &&
        entry.ventilation_state === 'control',
    );
    assert.ok(other, 'The same module needs a zero-power control.');
    await root().getByLabel('Scénario ISS', { exact: true }).selectOption(other.id);
    await ready(other.id);
    const control = await replay(other);
    assert.equal(await root().locator('[data-iss-ventilation]').count(), 0);
    assert.equal(await root().getAttribute('data-comparison-time-s'), '');
    assert.equal(
      Number(await root().getAttribute('data-time-s')),
      control.frames[presentationFrame(control)].time_s,
    );
    record('same_quartet_keeps_camera_and_requested_time_without_interpolation', {
      group: ventilationCase.ventilation_group_id,
      split: 'train',
      target_time_s: targetTime,
      has_distinct_observation_times: differingTime >= 0,
      observations,
      camera_position: position,
      camera_direction: direction,
      overview_camera_position: overviewPosition,
      overview_camera_direction: overviewDirection,
      reset_control: other.id,
    });
  } else {
    assert.ok(!ventilationOnly, 'A TRAIN ventilation quartet is required in ventilation-only mode.');
    assert.equal(await root().locator('[data-iss-ventilation]').count(), 0);
    record('legacy_export_keeps_original_controls');
  }

  if (!ventilationOnly) {
    await select(initial);
    const data = await replay(initial);
    const peak = presentationFrame(data);
    await frame(peak, data.frames[peak].time_s);
    await root().getByRole('button', { name: 'Ensemble', exact: true }).click();
    await page.waitForTimeout(400);
    const overviewHash = hash(await root().locator('canvas').screenshot());
    await root().getByRole('button', { name: 'Intérieur', exact: true }).click();
    await page.waitForTimeout(400);
    const insideHash = hash(await root().locator('canvas').screenshot());
    assert.notEqual(overviewHash, insideHash);
    record('inside_and_overview_cameras', { overviewHash, insideHash });

    const canvas = root().locator('canvas');
    await canvas.scrollIntoViewIfNeeded();
    const beforeDirection = await cameraValues('data-camera-direction');
    const beforePosition = await cameraValues('data-camera-position');
    const box = await canvas.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 75, box.y + box.height / 2 - 20, { steps: 8 });
    await page.mouse.up();
    await page.waitForTimeout(200);
    const afterDirection = await cameraValues('data-camera-direction');
    assert.notDeepEqual(beforeDirection, afterDirection, 'Dragging must change camera orientation.');
    await canvas.focus();
    let moved = beforePosition;
    for (const key of ['ArrowUp', 'ArrowLeft', 'ArrowDown', 'ArrowRight']) {
      await canvas.press(key);
      try {
        // Software WebGL can finish a queued render well after a fixed 100 ms
        // pause. Observe the actual camera; a blocked direction still times out.
        await page.waitForFunction(
          (previous) => {
            const value = document
              .querySelector('[data-iss-poc] canvas')
              ?.getAttribute('data-camera-position');
            return value?.split(',').some((coordinate, axis) => Number(coordinate) !== previous[axis]);
          },
          beforePosition,
          { timeout: 5000 },
        );
      } catch (error) {
        if (error.name !== 'TimeoutError') throw error;
      }
      moved = await cameraValues('data-camera-position');
      if (JSON.stringify(moved) !== JSON.stringify(beforePosition)) break;
    }
    assert.notDeepEqual(moved, beforePosition, 'Keyboard movement must change the real camera position.');
    assert.ok(
      [moved[0], -moved[2], moved[1]].every((value, axis) => value > 0 && value < data.scene.bounds_m[axis]),
    );
    record('actual_look_and_walk_interaction', {
      beforeDirection,
      afterDirection,
      beforePosition,
      afterPosition: moved,
      movement_observation_timeout_ms: 5000,
    });
    await root().getByRole('button', { name: 'Recentrer la caméra', exact: true }).click();
    await page.waitForTimeout(200);

    await root().getByRole('button', { name: 'Référence FDS', exact: true }).click();
    assert.equal(await root().getAttribute('data-display'), 'reference');
    await root().getByRole('button', { name: 'Erreurs', exact: true }).click();
    assert.equal(await root().getAttribute('data-display'), 'errors');
    await root().getByRole('button', { name: 'Prédiction ML', exact: true }).click();
    await root().getByLabel('Couche chaleur', { exact: true }).uncheck();
    assert.equal(await root().getByLabel('Couche fumée', { exact: true }).isChecked(), true);
    await capture('iss-smoke-only.png');
    await root().getByLabel('Couche chaleur', { exact: true }).check();
    await root().getByLabel('Couche fumée', { exact: true }).uncheck();
    await capture('iss-heat-only.png');
    await root().getByLabel('Couche fumée', { exact: true }).check();
    record('independent_heat_smoke_and_reference_controls');

    await frame(0, data.frames[0].time_s);
    if (data.frames.length > 1) {
      await root().getByRole('button', { name: 'Lire le scénario ISS', exact: true }).click();
      await page.waitForFunction(
        (time) => Number(document.querySelector('[data-iss-poc]')?.getAttribute('data-time-s')) > time,
        data.frames[0].time_s,
        { timeout: 20_000 },
      );
      const pause = root().getByRole('button', { name: 'Pause ISS', exact: true });
      if (await pause.count()) await pause.click();
      record('timeline_plays_exported_times');
    }
    await frame(peak, data.frames[peak].time_s);
    await capture('iss-presentation.png');
    await page.setViewportSize({ width: 1100, height: 800 });
    await page.waitForTimeout(400);
    const timeline = await root().locator('.iss-timeline').boundingBox();
    const slider = await root().getByLabel('Instant ISS', { exact: true }).boundingBox();
    const speed = await root().getByLabel('Vitesse de lecture ISS', { exact: true }).boundingBox();
    assert.ok(slider.width > timeline.width * 0.5, 'The timeline must receive most of the available width.');
    assert.ok(speed.width <= 66, 'Playback speed must remain a compact selector.');
    assert.ok(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2),
      'Laptop must not overflow horizontally.',
    );
    await capture('iss-laptop.png');
    record('laptop_layout_and_useful_timeline', {
      timeline_width: timeline.width,
      slider_width: slider.width,
      speed_width: speed.width,
    });
  }
  assert.equal(writes.length, 0, 'Viewer must not request new FDS or training jobs.');
  assert.deepEqual(errors, []);
  record('no_javascript_error_or_compute_submission');
} catch (error) {
  await capture('iss-failure.png').catch(() => {});
  throw error;
} finally {
  await writeFile(
    path.join(output, 'browser-report.json'),
    JSON.stringify(
      {
        checked_at: new Date().toISOString(),
        base,
        route,
        scope: ventilationOnly ? 'train-ventilation-quartet' : 'full-export',
        model_id: index?.model.id,
        checks,
        errors,
        writes,
        screenshots,
      },
      null,
      2,
    ),
  );
  await browser.close();
}
