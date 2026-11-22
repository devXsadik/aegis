import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: { include: ['src/**/*.test.{js,jsx}'] },     // Vitest; e2e/ belongs to Playwright
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.API_PROXY || 'http://localhost:8000',   // e2e tests point it at their own API
        changeOrigin: true,
        ws: true,
      },
    },
  },
})

