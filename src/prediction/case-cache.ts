/** Keep verified files on disk and only three recent files in memory. Never cache parsed frame arrays. */
const memory = new Map<string, ArrayBuffer>();
const pending = new Map<string, Promise<ArrayBuffer>>();
const cacheName = 'valley-predictions-v1';

async function verified(bytes: ArrayBuffer, sha: string) {
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(hash), value => value.toString(16).padStart(2, '0')).join('') === sha;
}

async function readBytes(url: string, sha: string, key: string) {
  let cache: Cache | undefined;
  try {
    cache = await caches.open(cacheName);
    const saved = await cache.match(key);
    if (saved) {
      const bytes = await saved.arrayBuffer();
      if (await verified(bytes, sha)) return bytes;
      await cache.delete(key);
    }
  } catch { /* Private browsing or storage limits: network and bounded memory still work. */ }
  const response = await fetch(url, { cache: 'no-cache', signal: AbortSignal.timeout(30_000) });
  if (!response.ok) throw new Error('Scenario unavailable. Reload the complete model export.');
  const bytes = await response.arrayBuffer();
  if (!(await verified(bytes, sha))) throw new Error('Scenario integrity check failed: unexpected SHA256.');
  try { await cache?.put(key, new Response(bytes, { headers: { 'Content-Type': 'application/json' } })); }
  catch { /* A full cache must not prevent the selected scene from opening. */ }
  return bytes;
}

/** The hash is part of the cache key: a new model export cannot reuse stale predictions. */
export function caseBytes(url: string, sha: string, signal?: AbortSignal): Promise<ArrayBuffer> {
  if (signal?.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'));
  const key = `${url}?verified=${sha}`;
  const recent = memory.get(key);
  if (recent) {
    memory.delete(key); memory.set(key, recent);
    return Promise.resolve(recent);
  }
  let request = pending.get(key);
  if (!request) {
    request = readBytes(url, sha, key).then(bytes => {
      memory.set(key, bytes);
      while (memory.size > 3) memory.delete(memory.keys().next().value!);
      return bytes;
    }).finally(() => pending.delete(key));
    pending.set(key, request);
  }
  if (!signal) return request;
  // Navigation cancels its own subscriber, not a shared preload or another room request.
  return new Promise((resolve, reject) => {
    const abort = () => reject(new DOMException('Aborted', 'AbortError'));
    signal.addEventListener('abort', abort, { once: true });
    request!.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
  });
}

export async function isCaseCached(url: string, sha: string) {
  try { return !!(await (await caches.open(cacheName)).match(`${url}?verified=${sha}`)); }
  catch { return false; }
}
