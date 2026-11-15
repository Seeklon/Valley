import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile, copyFile, rename, rm, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Use a complete, independently verified iss-poc-1 export. Never runs training.
const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const source = process.argv[2] && path.resolve(process.argv[2]);
if (!source) throw new Error('Usage: npm run data:predictions -- /path/to/verified/demo');
const hash = data => createHash('sha256').update(data).digest('hex');
const rawIndex = await readFile(path.join(source, 'index.json'));
const index = JSON.parse(rawIndex);
if (index.schema_version !== 'iss-poc-1' || !index.cases?.length || !/^[a-f0-9]{64}$/.test(index.model?.weights_sha256))
  throw new Error('Incomplete or unsupported prediction index.');
const dest = path.join(root, 'public/poc/iss');
const token = Date.now();
const stage = path.join(root, `public/poc/.iss-stage-${token}`);
const backup = path.join(root, `artifacts/prediction-backups/${token}`);
await mkdir(stage, { recursive: true });
try {
  for (const entry of index.cases) {
    const relative = entry.url.replace(/^\.\//, '').replace(/^\/poc\/iss\//, '');
    if (!/^(?:[\w-]+\/)*[\w.-]+\.json$/.test(relative) || relative.split('/').includes('..'))
      throw new Error(`Unsafe case path: ${entry.id}`);
    const bytes = await readFile(path.join(source, relative));
    if (hash(bytes) !== entry.sha256) throw new Error(`Hash mismatch: ${entry.id}`);
    const data = JSON.parse(bytes);
    if (data.id !== entry.id || data.layout_id !== entry.layout_id || data.module_id !== entry.module_id)
      throw new Error(`Case identity mismatch: ${entry.id}`);
    for (const channel of ['heat', 'smoke'])
      if (data.score_thresholds[channel] !== index.model.score_thresholds[channel])
        throw new Error(`Model thresholds mismatch: ${entry.id}`);
    if (data.heat_delta_c !== index.model.heat_delta_c || data.smoke_threshold_kg_m3 !== index.model.smoke_threshold_kg_m3)
      throw new Error(`Physical thresholds mismatch: ${entry.id}`);
    await mkdir(path.dirname(path.join(stage, relative)), { recursive: true });
    await copyFile(path.join(source, relative), path.join(stage, relative));
    // Detect a source being updated during the import, including the copy itself.
    if (hash(await readFile(path.join(stage, relative))) !== entry.sha256)
      throw new Error(`Source changed during copy: ${entry.id}`);
  }
  await writeFile(path.join(stage, 'index.json'), rawIndex);
  await writeFile(path.join(stage, 'installation.json'), JSON.stringify({
    imported_at: new Date().toISOString(), cases: index.cases.length,
    index_sha256: hash(rawIndex), weights_sha256: index.model.weights_sha256,
    dataset_sha256: index.model.dataset_sha256,
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
