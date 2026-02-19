import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const proxyTarget = env.VITE_PROXY_TARGET || "http://localhost:8000";

  return {
    plugins: [react()],
    test: {
    environment: "jsdom",
    setupFiles: "./src/setupTests.js",
    globals: true,
  },
  server: {
    host: true,          // ✅ bind 0.0.0.0 (ให้เครื่องอื่นเข้าถึงได้)
    port: 5173,
    strictPort: true,

    // ✅ แก้ HMR websocket ให้ชี้ไป IP ที่เปิดเว็บอยู่จริง
    hmr: {
      protocol: "ws",
      host: "10.32.70.136",
      port: 5173,
      clientPort: 8000,  // ✅ ช่วยในกรณีอยู่หลัง NAT/Proxy/Docker
    },

    proxy: {
      "/api": {
        target: proxyTarget,
        changeOrigin: true,
      },
    },
  },
  };
});
