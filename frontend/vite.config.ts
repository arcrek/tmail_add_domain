import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const proxy = {
  target: 'http://127.0.0.1:8000',
}

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/domains': proxy,
      '/accounts': proxy,
      '/token': proxy,
      '/me': proxy,
      '/messages': proxy,
      '/sources': proxy,
      '/site': proxy,
      '/admin/api': proxy,
    },
  },
  build: {
    outDir: 'dist',
  },
})
