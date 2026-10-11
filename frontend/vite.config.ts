import { defineConfig } from 'vite'

// Dev server proxies /api to FastAPI on 127.0.0.1:8000. Both bind to localhost only.
export default defineConfig({
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  preview: {
    host: '127.0.0.1',
  },
})
