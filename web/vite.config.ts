import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const root = path.dirname(fileURLToPath(import.meta.url));
const cyberdeckUi = path.resolve(root, "../../cyberdeck-ui");

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@cyberdeck/ui/tokens.css": path.join(
        cyberdeckUi,
        "dist/styles/tokens.css",
      ),
      "@cyberdeck/ui/styles.css": path.join(
        cyberdeckUi,
        "dist/styles/globals.css",
      ),
      "@cyberdeck/ui/tailwind-preset": path.join(
        cyberdeckUi,
        "dist/tailwind/preset-v3.js",
      ),
      "@cyberdeck/ui": path.join(cyberdeckUi, "dist/index.js"),
    },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/data": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
