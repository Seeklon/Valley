import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, writeFile, rename, rm, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { gunzipSync } from 'node:zlib';

// Use a complete, independently verified iss-poc-1 export. Never runs training.
const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const args = process.argv.slice(2);
if (args.some(arg => arg.startsWith('--') && !['--ensure', '--lab'].includes(arg)))
  throw new Error('Supported options: --ensure, --lab, and one export directory.');
const positional = args.filter(arg => !arg.startsWith('--'));
if (positional.length > 1) throw new Error('Supply at most one export directory.');
const source = path.resolve(positional[0] ?? path.join(root, 'data/predictions/ignis-20261115-vent'));
const ensure = args.includes('--ensure');
const appRoot = args.includes('--lab') ? path.join(root, 'web') : root;
const hash = data => createHash('sha256').update(data).digest('hex');
const dest = path.join(appRoot, 'public/poc/iss');
let rawIndex = await readFile(path.join(source, 'index.json'));
let customInstallation = false;
// An explicitly imported future model survives the automatic build hook.
if (ensure && !positional.length) {
  try {
    const installed = JSON.parse(await readFile(path.join(dest, 'installation.json')));
    if (installed.source_kind === 'custom') {
      customInstallation = true;
      const bytes = await readFile(path.join(dest, 'index.json'));
      if (hash(bytes) !== installed.index_sha256 ||
          JSON.parse(bytes).model?.weights_sha256 !== installed.weights_sha256)
        throw new Error('Custom prediction index changed; import the verified export again.');
      rawIndex = bytes;
    }
  } catch (error) {
    if (customInstallation || error.code !== 'ENOENT') throw error;
  }
}
const index = JSON.parse(rawIndex);
if (index.schema_version !== 'iss-poc-1' || !Array.isArray(index.cases) || !index.cases.length || !/^[a-f0-9]{64}$/.test(index.model?.weights_sha256))
  throw new Error('Incomplete or unsupported prediction index.');
const entries = index.cases.map(entry => {
  const relative = entry.url.replace(/^\.\//, '').replace(/^\/poc\/iss\//, '');
  if (!/^(?:[\w-]+\/)*[\w.-]+\.json$/.test(relative) || relative.split('/').includes('..'))
    throw new Error(`Unsafe case path: ${entry.id}`);
  return { entry, relative };
});
if (new Set(entries.map(({ relative }) => relative)).size !== entries.length ||
    new Set(index.cases.map(entry => entry.id)).size !== entries.length)
  throw new Error('Duplicate prediction case or file.');

function validateCase(entry, bytes) {
    if (hash(bytes) !== entry.sha256) throw new Error(`Hash mismatch: ${entry.id}`);
    const data = JSON.parse(bytes);
    if (data.id !== entry.id || data.layout_id !== entry.layout_id || data.module_id !== entry.module_id)
      throw new Error(`Case identity mismatch: ${entry.id}`);
    for (const channel of ['heat', 'smoke'])
      if (data.score_thresholds[channel] !== index.model.score_thresholds[channel])
        throw new Error(`Model thresholds mismatch: ${entry.id}`);
    if (data.heat_delta_c !== index.model.heat_delta_c || data.smoke_threshold_kg_m3 !== index.model.smoke_threshold_kg_m3)
      throw new Error(`Physical thresholds mismatch: ${entry.id}`);
}

async function isCurrent() {
  try {
    if (hash(await readFile(path.join(dest, 'index.json'))) !== hash(rawIndex)) return false;
    for (const { entry, relative } of entries) validateCase(entry, await readFile(path.join(dest, relative)));
    return true;
  } catch (error) {
    if (error.code && error.code !== 'ENOENT') throw error;
    return false;
  }
}

async function install() {
  if (ensure && await isCurrent()) {
    console.log(JSON.stringify({ verified: true, cases: entries.length, destination: dest,
      weights_sha256: index.model.weights_sha256, reused: true }));
    return;
  }
  if (customInstallation) throw new Error('Custom prediction files changed; import the verified export again.');
  const token = randomUUID();
  const stage = path.join(appRoot, `public/poc/.iss-stage-${token}`);
  const backup = path.join(root, `artifacts/prediction-backups/${token}`);
  await mkdir(stage, { recursive: true });
  try {
  for (const { entry, relative } of entries) {
    let bytes;
    try { bytes = await readFile(path.join(source, relative)); }
    catch (error) {
      if (error.code !== 'ENOENT') throw error;
      bytes = gunzipSync(await readFile(path.join(source, relative + '.gz')));
    }
    validateCase(entry, bytes);
    await mkdir(path.dirname(path.join(stage, relative)), { recursive: true });
    await writeFile(path.join(stage, relative), bytes);
    // Recheck the actual bytes that will be served, including decompressed files.
    if (hash(await readFile(path.join(stage, relative))) !== entry.sha256)
      throw new Error(`Source changed during copy: ${entry.id}`);
  }
  await writeFile(path.join(stage, 'index.json'), rawIndex);
  await writeFile(path.join(stage, 'installation.json'), JSON.stringify({
    imported_at: new Date().toISOString(), cases: index.cases.length,
    index_sha256: hash(rawIndex), weights_sha256: index.model.weights_sha256,
    dataset_sha256: index.model.dataset_sha256,
    source_kind: positional.length ? 'custom' : 'bundled',
  }, null, 2));
  const exists = await stat(dest).then(() => true, () => false);
  if (exists) { await mkdir(path.dirname(backup), { recursive: true }); await rename(dest, backup); }
  try { await rename(stage, dest); }
  catch (error) { if (exists) await rename(backup, dest); throw error; }
  console.log(JSON.stringify({ cases: index.cases.length, weights_sha256: index.model.weights_sha256,
    destination: dest, previous_export: exists ? backup : null }, null, 2));
} catch (error) {
  await rm(stage, { recursive: true, force: true });
  throw error;
}
}

await install();
