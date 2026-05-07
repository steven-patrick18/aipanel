import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 8055,
    strictPort: true,
    proxy: {
      // For local dev: proxy API calls to the running backend.
      // Default target is the mock (port 8800). Set VITE_API_TARGET to
      // http://127.0.0.1:8000 when running the real backend from
      // dev/start.ps1, e.g.:
      //   $env:VITE_API_TARGET="http://127.0.0.1:8000"; npm run dev
      "/api": {
        target: process.env.VITE_API_TARGET || "http://127.0.0.1:8800",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    target: "es2022",
  },
});
