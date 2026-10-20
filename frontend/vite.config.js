import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  root: "dashboard",
  plugins: [react()],
  server: {
    port: 5175,
    proxy: {
      "/api": "http://127.0.0.1:8070",
    },
  },
  build: {
    outDir: "../../static/dashboard_build",
    emptyOutDir: true,
  },
});
