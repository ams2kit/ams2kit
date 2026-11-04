// The Python server (ams2kit/ui/server.py) serves the built page: index.html at "/", everything else
// under /static/. The build output is committed so running ams2kit needs no Node.
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const backend = "http://127.0.0.1:8765";

// server.py refuses requests whose Origin is not its own page (it writes files and starts programs),
// so the dev proxy drops the Vite page's Origin header.
const proxy = { target: backend, changeOrigin: true, configure: p => p.on("proxyReq", req => req.removeHeader("origin")) };

export default defineConfig(({ command }) => ({
  plugins: [vue()],
  base: command === "build" ? "/static/" : "/",
  build: {
    outDir: fileURLToPath(new URL("../ams2kit/ui/static", import.meta.url)),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: { "/api": proxy, "/file": proxy },
  },
}));
