import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Both the dev server and `vite preview` proxy /api to the FastAPI backend, so
// the frontend always talks to a single origin and CORS stays irrelevant.
// Point OMNICIENT_API_URL at the backend when running under Docker Compose.
const proxy = {
  '/api': {
    target: process.env.OMNICIENT_API_URL ?? 'http://127.0.0.1:8000',
    changeOrigin: true,
  },
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, host: true, proxy },
  preview: { port: 5173, host: true, proxy },
})
