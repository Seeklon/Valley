import { assetUrl, loadIndex } from './prediction/catalog';
import { caseBytes, isCaseCached } from './prediction/case-cache';
import { issCaseUrl } from './prediction/iss-poc';

/** Warm every transition/texture and verified scenario from the landing page, with bounded concurrency. */
export async function startScenePreload() {
  if (new URLSearchParams(location.search).has('export')) return;
  const status = document.createElement('div');
  status.id = 'scene-preload';
  status.textContent = 'Preparing scenes…';
  status.setAttribute('role', 'status');
  document.querySelector('#app')!.append(status);
  let ready = 0, failed = 0, onDemand = 0;
  const jobs: (() => Promise<void>)[] = [];
  const sources = await Promise.allSettled([
    loadIndex(new AbortController().signal),
    fetch(assetUrl('scene-assets.json'), { cache: 'no-cache' }).then(async response => {
      if (!response.ok) throw new Error('Scene manifest unavailable');
      return await response.json() as { files: string[] };
    }),
  ]);
  const index = sources[0].status === 'fulfilled' ? sources[0].value : undefined;
  const assets = sources[1].status === 'fulfilled' ? sources[1].value.files : [];
  failed += sources.filter(result => result.status === 'rejected').length;
  const cases = index?.cases ?? [];
  const priority = new Set(Object.values(index?.example_cases?.modules ?? {}));
  const addCases = (first: boolean) => cases.filter(entry => priority.has(entry.id) === first).forEach(entry => jobs.push(async () => {
    const url = assetUrl(issCaseUrl(entry.url));
    await caseBytes(url, entry.sha256);
    if (!(await isCaseCached(url, entry.sha256))) onDemand++;
  }));
  addCases(true);
  assets.forEach(path => jobs.push(async () => {
    const response = await fetch(assetUrl(path), { cache: 'no-cache', signal: AbortSignal.timeout(30_000) });
    if (!response.ok) throw new Error(`Scene asset unavailable: ${path}`);
    // Drain the response into the browser's HTTP cache, without retaining large image buffers in JS.
    const reader = response.body?.getReader();
    if (reader) while (!(await reader.read()).done) { /* Streaming warm-up. */ }
  }));
  addCases(false);
  const total = jobs.length;
  let cursor = 0;
  status.dataset.state = 'loading';
  status.dataset.total = String(total);
  const update = () => {
    status.dataset.loaded = String(ready);
    status.textContent = `Preloading scenes · ${Math.min(100, Math.round((ready + failed) / Math.max(1, total) * 100))}%`;
  };
  update();
  await Promise.all(Array.from({ length: 3 }, async () => {
    while (cursor < jobs.length) {
      const job = jobs[cursor++];
      try { await job(); ready++; } catch { failed++; }
      update();
      await new Promise(resolve => setTimeout(resolve, 0));
    }
  }));
  status.dataset.state = failed || onDemand ? 'partial' : 'ready';
  status.dataset.failed = String(failed);
  status.dataset.onDemand = String(onDemand);
  status.textContent = failed || onDemand ? 'Scenes prepared · some files load on demand' : 'All scenes ready';
  if (!failed && !onDemand) setTimeout(() => { status.hidden = true; }, 5000);
}
