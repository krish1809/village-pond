import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base: './' makes the built asset paths relative, so the same dist/ works
// whether it's served from the site root by FastAPI or from a sub-path.
//
// The dev server proxies the API routes to the FastAPI backend on :8000, so in
// development the front-end can call /analyzeArea on its own origin exactly like
// it does in production (where FastAPI serves both).
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    proxy: {
      '/analyzeArea': 'http://localhost:8000',
      '/analyzeContour': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
