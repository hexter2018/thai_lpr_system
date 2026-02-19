import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const proxyTarget = env.VITE_PROXY_TARGET || "http://localhost:8000";
  const hmrHost = env.VITE_HMR_HOST;
  const hmrClientPort = env.VITE_HMR_CLIENT_PORT
    ? Number(env.VITE_HMR_CLIENT_PORT)
    : undefined;

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
      ...(hmrHost ? { host: hmrHost } : {}),
      ...(hmrClientPort ? { clientPort: hmrClientPort } : {}),
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
