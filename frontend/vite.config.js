import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: process.env.TAURI_DEV_HOST || false,
    proxy: {
      "/auth": "http://127.0.0.1:8000",
      "/chat": "http://127.0.0.1:8000",
      "/restaurants": "http://127.0.0.1:8000",
      "/search": "http://127.0.0.1:8000",
      "/mealplan": "http://127.0.0.1:8000",
      "/api": "http://127.0.0.1:8000",
      "/my-orders": "http://127.0.0.1:8000",
      "/owner": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/categories": "http://127.0.0.1:8000",
      "/nearby": "http://127.0.0.1:8000",
      "/taste": "http://127.0.0.1:8000",
      "/feedback": "http://127.0.0.1:8000",
      "/orders": "http://127.0.0.1:8000",
      "/cart": "http://127.0.0.1:8000",
      "/checkout": "http://127.0.0.1:8000",
      "/ai": "http://127.0.0.1:8000",
      "/group": "http://127.0.0.1:8000",
    },
  },
});
