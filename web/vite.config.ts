import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dashboard is built straight into the Python package, which serves it at
// "/" with assets under "/static". `npm run dev` proxies the API to a running
// `m3allema serve` on port 8765.
export default defineConfig({
  plugins: [react()],
  base: "/static/",
  build: {
    outDir: "../src/m3allema/server/static",
    emptyOutDir: true,
    assetsDir: "assets",
  },
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:8765", ws: true },
    },
  },
});
