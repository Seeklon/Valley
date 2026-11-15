import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

// Capture the actual rendered rooms, retaining the existing site's preview filenames/layout.
const base = (process.env.POV_URL ?? 'http://127.0.0.1:5182').replace(/\/$/, '');
const output = path.resolve('public/rooms');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true,
  executablePath: process.env.BROWSER_PATH || undefined,
  args: process.platform === 'linux' ? ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] : [],
});
const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1, reducedMotion: 'reduce' });
page.setDefaultTimeout(90_000);
const captures = [];
try {
  for (const environment of ['iss', 'earth']) {
    await page.goto(`${base}/?nogl&hub&env=${environment}&open=prev`, { waitUntil: 'domcontentloaded' });
    for (const room of ['prev', 'det', 'sup', 'fun', 'si']) {
      if (room !== 'prev') await page.locator(`[data-go="${room}"]`).click();
      await page.waitForFunction(id => {
        const root = document.querySelector('#prediction-room');
        const button = document.querySelector(`[data-go="${id}"]`);
        return button?.getAttribute('aria-pressed') === 'true' && root?.dataset.state === 'ready' && root.dataset.triangles > 0;
      }, room);
      // A rendered frame must exist; shader compilation can finish after data loading.
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const filename = `v_${room}${environment === 'earth' ? 'e' : ''}.jpg`;
      await page.screenshot({ path: path.join(output, filename), type: 'jpeg', quality: 88,
        clip: { x: 384, y: 194, width: 512, height: 512 },
        style: '#inbar,#pars,#panel,#ptab,#replay,#tags,#fade,#vig{visibility:hidden!important}',
      });
      const details = await page.locator('#prediction-room').evaluate(el => ({ case_id: el.dataset.caseId, weights_sha256: el.dataset.modelSha, time_s: Number(el.dataset.timeS) }));
      captures.push({ filename, environment, room, ...details });
      console.log(JSON.stringify(captures[captures.length - 1]));
    }
  }
  await mkdir('artifacts', { recursive: true });
  await writeFile('artifacts/preview-provenance.json', JSON.stringify(captures, null, 2));
} finally { await browser.close(); }
