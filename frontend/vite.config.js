import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,          // ✅ bind 0.0.0.0 (ให้เครื่องอื่นเข้าถึงได้)
    port: 5173,
    strictPort: true,

    // ✅ แก้ HMR websocket ให้ชี้ไป IP ที่เปิดเว็บอยู่จริง
    hmr: {
      protocol: "ws",
      host: "10.32.70.136",
      port: 5173,
      clientPort: 5173,  // ✅ ช่วยในกรณีอยู่หลัง NAT/Proxy/Docker
    },

    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});