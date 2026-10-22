import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The browser talks to /api; Vite forwards it to the FastAPI backend (no CORS setup needed).
const backend = {
  '/api': {
    target: process.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000',
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/api/, ''),
  },
}

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: backend },
  preview: { port: 5173, proxy: backend },
})
