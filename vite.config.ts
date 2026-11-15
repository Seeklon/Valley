import { defineConfig } from 'vite';
import { readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const publicDir = fileURLToPath(new URL('./public', import.meta.url));
const sceneFiles = (directory = ''): string[] => readdirSync(path.join(publicDir, directory), { withFileTypes: true })
  .filter(entry => entry.name !== 'poc' && !entry.name.startsWith('.'))
  .flatMap(entry => entry.isDirectory() ? sceneFiles(path.posix.join(directory, entry.name))
    : /\.(?:jpg|png|webp|json|bin|glb)$/i.test(entry.name) ? [path.posix.join(directory, entry.name)] : []);

// Relative base: the built site works from any folder of any static host (the VPS path is not fixed yet).
export default defineConfig({
  base: './',
  plugins: [{ name: 'scene-preload-manifest', generateBundle() {
    this.emitFile({ type: 'asset', fileName: 'scene-assets.json', source: JSON.stringify({ files: sceneFiles() }) });
  }, configureServer(server) {
    server.middlewares.use((request, response, next) => {
      if (request.url?.split('?')[0] !== '/scene-assets.json') return next();
      response.setHeader('Content-Type', 'application/json');
      response.end(JSON.stringify({ files: sceneFiles() }));
    });
  } }],
  build: { target: 'es2020', chunkSizeWarningLimit: 1200 },
});
