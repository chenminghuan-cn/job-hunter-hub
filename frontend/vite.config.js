import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backend = 'http://127.0.0.1:8010'
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5199,
    proxy: {
      '/api': backend,
      '/a2a': backend,
      '/.well-known': backend,
    },
  },
})
