import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // The client talks to /api; everything is forwarded to uvicorn.
      // Set VITE_API_BASE=http://localhost:8000 to bypass this if the chat
      // stream ever arrives buffered instead of token by token.
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
