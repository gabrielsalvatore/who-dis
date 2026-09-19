import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend holds every provider key. The client only ever talks to /api on
// this origin, so the paid-provider proxy is never exposed directly.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
