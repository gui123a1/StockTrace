import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端端口可用环境变量覆盖（默认 8000），例如本机 8000 被其他服务占用时：
// VITE_API_TARGET=http://localhost:8001 npm run dev
const apiTarget = process.env.VITE_API_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
})
