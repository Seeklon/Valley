import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync, spawnSync } from 'node:child_process';
import { copyFile, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const importer = fileURLToPath(new URL('./import-predictions.mjs', import.meta.url));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const bundlePath = root => path.join(root, 'data/predictions/ignis-20261115-vent');
const targetPath = root => path.join(root, 'public/poc/iss');

async function fixture(t) {
  const root = await mkdtemp(path.join(tmpdir(), 'ignis-predictions-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(path.join(root, 'scripts'));
  await copyFile(importer, path.join(root, 'scripts/import-predictions.mjs'));
  return root;
}

async function exportCase(directory, id = 'example') {
  const physical = { score_thresholds: { heat: 0.9, smoke: 0.8 }, heat_delta_c: 5,
    smoke_threshold_kg_m3: 1e-6 };
  const data = { id, layout_id: 'layout', module_id: 'laboratory', ...physical };
  const bytes = Buffer.from(JSON.stringify(data) + '\r\n');
  const index = { schema_version: 'iss-poc-1',
    model: { weights_sha256: 'a'.repeat(64), dataset_sha256: 'b'.repeat(64), ...physical },
    cases: [{ id, layout_id: data.layout_id, module_id: data.module_id,
      url: `/poc/iss/cases/${id}.json`, sha256: sha(bytes) }] };
  await mkdir(path.join(directory, 'cases'), { recursive: true });
  await writeFile(path.join(directory, `cases/${id}.json.gz`), gzipSync(bytes));
  const indexBytes = Buffer.from(JSON.stringify(index, null, 2).replaceAll('\n', '\r\n') + '\r\n');
  await writeFile(path.join(directory, 'index.json'), indexBytes);
  return { bytes, indexBytes };
}

const run = (root, ...args) => execFileSync(process.execPath,
  [path.join(root, 'scripts/import-predictions.mjs'), ...args], { encoding: 'utf8' });
const fail = (root, ...args) => {
  const result = spawnSync(process.execPath,
    [path.join(root, 'scripts/import-predictions.mjs'), ...args], { encoding: 'utf8' });
  assert.notEqual(result.status, 0);
  return result.stderr;
};

test('restores gzip bytes exactly, reuses verified files and repairs a damaged bundled case', async t => {
  const root = await fixture(t);
  const { bytes, indexBytes } = await exportCase(bundlePath(root));
  run(root, '--ensure');
  const dest = targetPath(root);
  assert.deepEqual(await readFile(path.join(dest, 'index.json')), indexBytes);
  assert.deepEqual(await readFile(path.join(dest, 'cases/example.json')), bytes);
  const installation = await readFile(path.join(dest, 'installation.json'));
  assert.equal(JSON.parse(run(root, '--ensure')).reused, true);
  assert.deepEqual(await readFile(path.join(dest, 'installation.json')), installation);
  await writeFile(path.join(dest, 'cases/example.json'), 'damaged');
  run(root, '--ensure');
  assert.deepEqual(await readFile(path.join(dest, 'cases/example.json')), bytes);
});

test('rejects corrupted source data without replacing the installed export', async t => {
  const root = await fixture(t);
  const { bytes } = await exportCase(bundlePath(root));
  run(root);
  await writeFile(path.join(bundlePath(root), 'cases/example.json.gz'), gzipSync('wrong bytes'));
  assert.match(fail(root), /Hash mismatch/);
  assert.deepEqual(await readFile(path.join(targetPath(root), 'cases/example.json')), bytes);
});

test('preserves an explicitly imported model across build hooks and refuses damaged custom files', async t => {
  const root = await fixture(t);
  await exportCase(bundlePath(root));
  const custom = path.join(root, 'custom');
  const { bytes } = await exportCase(custom, 'custom-case');
  run(root, custom);
  assert.equal(JSON.parse(run(root, '--ensure')).reused, true);
  assert.deepEqual(await readFile(path.join(targetPath(root), 'cases/custom-case.json')), bytes);
  await rm(path.join(targetPath(root), 'cases/custom-case.json'));
  assert.match(fail(root, '--ensure'), /Custom prediction files changed/);
  const current = JSON.parse(await readFile(path.join(targetPath(root), 'index.json')));
  assert.equal(current.cases[0].id, 'custom-case');
});

test('restores the laboratory export independently', async t => {
  const root = await fixture(t);
  const { bytes } = await exportCase(bundlePath(root));
  run(root, '--ensure', '--lab');
  assert.deepEqual(await readFile(path.join(root, 'web/public/poc/iss/cases/example.json')), bytes);
  await assert.rejects(readFile(path.join(targetPath(root), 'index.json')), { code: 'ENOENT' });
});

test('rejects a case path outside the export', async t => {
  const root = await fixture(t);
  await exportCase(bundlePath(root));
  const indexFile = path.join(bundlePath(root), 'index.json');
  const index = JSON.parse(await readFile(indexFile));
  index.cases[0].url = '../../outside.json';
  await writeFile(indexFile, JSON.stringify(index));
  assert.match(fail(root), /Unsafe case path/);
  await assert.rejects(readFile(path.join(targetPath(root), 'index.json')), { code: 'ENOENT' });
});
