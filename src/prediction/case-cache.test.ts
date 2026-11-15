import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const encode = (value: string) => new TextEncoder().encode(value).buffer;
const hash = async (bytes: ArrayBuffer) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), n => n.toString(16).padStart(2, '0')).join('');

describe('verified prediction preloading', () => {
  const saved = new Map<string, Response>();
  beforeEach(() => {
    vi.resetModules(); saved.clear();
    vi.stubGlobal('caches', { open: async () => ({
      match: async (key: string) => saved.get(key)?.clone(),
      put: async (key: string, value: Response) => { saved.set(key, value.clone()); },
      delete: async (key: string) => saved.delete(key),
    }) });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('shares a preload with navigation and does not fetch an already cached case again', async () => {
    const bytes = encode('test-only export'), sha = await hash(bytes);
    const fetch = vi.fn(async () => new Response(bytes)); vi.stubGlobal('fetch', fetch);
    const { caseBytes, isCaseCached } = await import('./case-cache');
    const [a, b] = await Promise.all([caseBytes('https://site.test/case.json', sha), caseBytes('https://site.test/case.json', sha)]);
    expect(a).toEqual(b); expect(fetch).toHaveBeenCalledTimes(1);
    expect(await isCaseCached('https://site.test/case.json', sha)).toBe(true);
    vi.resetModules();
    expect(await (await import('./case-cache')).caseBytes('https://site.test/case.json', sha)).toEqual(bytes);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('separates new model output by content hash and refuses corrupted network bytes', async () => {
    const old = encode('old output'), next = encode('new output');
    const fetch = vi.fn().mockResolvedValueOnce(new Response(old)).mockResolvedValueOnce(new Response(next)).mockResolvedValueOnce(new Response(old));
    vi.stubGlobal('fetch', fetch);
    const { caseBytes } = await import('./case-cache');
    await caseBytes('https://site.test/case.json', await hash(old));
    expect(await caseBytes('https://site.test/case.json', await hash(next))).toEqual(next);
    await expect(caseBytes('https://site.test/bad.json', await hash(next))).rejects.toThrow('SHA256');
    expect(saved.size).toBe(2);
  });

  it('repairs a corrupted cache and still opens scenes when disk storage is full', async () => {
    const bytes = encode('valid output'), sha = await hash(bytes), url = 'https://site.test/case.json';
    saved.set(`${url}?verified=${sha}`, new Response('corrupted'));
    const fetch = vi.fn(async () => new Response(bytes)); vi.stubGlobal('fetch', fetch);
    expect(await (await import('./case-cache')).caseBytes(url, sha)).toEqual(bytes);
    expect(fetch).toHaveBeenCalledTimes(1);
    vi.resetModules();
    vi.stubGlobal('caches', { open: async () => { throw new Error('quota'); } });
    expect(await (await import('./case-cache')).caseBytes(url, sha)).toEqual(bytes);
  });

  it('cancels one navigation without aborting the shared preload', async () => {
    const bytes = encode('test-only export'), sha = await hash(bytes);
    let finish!: (response: Response) => void;
    const fetch = vi.fn(() => new Promise<Response>(resolve => { finish = resolve; })); vi.stubGlobal('fetch', fetch);
    const { caseBytes } = await import('./case-cache');
    const preload = caseBytes('https://site.test/case.json', sha);
    const controller = new AbortController();
    const navigation = caseBytes('https://site.test/case.json', sha, controller.signal);
    const aborted = expect(navigation).rejects.toMatchObject({ name: 'AbortError' });
    controller.abort(); await aborted;
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    finish(new Response(bytes));
    expect(await preload).toEqual(bytes);
  });
});
