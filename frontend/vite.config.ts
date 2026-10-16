import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies API calls to FastAPI, so the browser sees one origin:
// no CORS configuration is needed on the backend, and the API key never leaves localhost.
const API = process.env.DOCUMIND_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": { target: API, changeOrigin: true },
      "/health": { target: API, changeOrigin: true },
    },
  },
  preview: {
    port: 4173,
    proxy: {
      "/v1": { target: API, changeOrigin: true },
      "/health": { target: API, changeOrigin: true },
    },
  },
});
