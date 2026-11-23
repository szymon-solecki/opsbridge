import { defineConfig } from 'vite'

export default defineConfig({
  server: { proxy: Object.fromEntries(['/api/dashboard', '/api/auth'].map(prefix => [
    prefix, { target: 'http://127.0.0.1:8000', rewrite: (path: string) => path.slice(4) },
  ])) },
})
