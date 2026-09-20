import os from 'node:os'
import path from 'node:path'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  cacheDir: path.join(os.tmpdir(), 'northstar-vite-cache'),
  build: {
    emptyOutDir: false,
    assetsDir: '',
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8002',
    },
  },
})


