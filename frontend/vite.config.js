import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "node",
    include: ["src/**/*.test.js", "src/**/*.test.jsx"],
    testTimeout: 60000,
  },
  server: {
    port: 5173,
    host: process.env.TAURI_DEV_HOST || false,
    proxy: Object.fromEntries(
      ["/auth", "/chat", "/restaurants", "/search", "/mealplan", "/api",
       "/my-orders", "/owner", "/health", "/categories", "/nearby",
       "/taste", "/feedback", "/orders", "/cart", "/checkout", "/ai", "/group"]
        .map((p) => [p, {
          target: process.env.VITE_API_TARGET || "http://127.0.0.1:8000",
          changeOrigin: true,
        }])
    ),
  },
});
