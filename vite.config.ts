import { defineConfig } from 'vite';

// Relative base: the built site works from any folder of any static host (the VPS path is not fixed yet).
export default defineConfig({
  base: './',
  build: { target: 'es2020', chunkSizeWarningLimit: 1200 },
});
