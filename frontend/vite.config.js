import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/agent": {
        target: "http://127.0.0.1:8080",
        changeOrigin: true
      },
      "/file": {
        target: "http://127.0.0.1:8080",
        changeOrigin: true
      }
    }
  }
});
