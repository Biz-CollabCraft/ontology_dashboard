import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const configuredBase = process.env.VITE_APP_BASE_PATH?.trim();
const githubPagesBase = process.env.GITHUB_PAGES === "1"
  ? "/agentic-ontology-dashboard/"
  : "/";
const appBase = configuredBase
  ? `/${configuredBase.replace(/^\/+|\/+$/g, "")}/`
  : githubPagesBase;

const apiProxy = {
  "/api": { target: process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000" },
  "/health": { target: process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000" },
  "/docs": { target: process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000" },
  "/redoc": { target: process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000" },
  "/openapi.json": { target: process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000" },
};

function interactiveTeamShareRoute(): Plugin {
  const rewrite = (
    request: { url?: string },
    response: { writeHead: (code: number, headers: Record<string,string>) => void; end: () => void },
    next: () => void,
  ) => {
    const url = request.url ?? "";
    const suffixIndex = url.search(/[?#]/);
    const pathname = suffixIndex === -1 ? url : url.slice(0, suffixIndex);
    if (pathname === "/team-share-adaptive") {
      request.url = `/index.html${suffixIndex === -1 ? "" : url.slice(suffixIndex)}`;
    }
    next();
  };
  return {
    name: "interactive-team-share-route",
    configureServer(server) {
      server.middlewares.use(rewrite);
    },
    configurePreviewServer(server) {
      server.middlewares.use(rewrite);
    },
  };
}

export default defineConfig({
  base: appBase,
  build: { rollupOptions: { input: { app: "index.html", factory: "factory-status-original/index.html" } } },
  plugins: [interactiveTeamShareRoute(), react()],
  // ManufacturingApp is route-lazy, so Vite's initial source scan does not
  // always discover its heavy UI dependencies before the first browser load.
  // Pre-bundle them during cold starts to avoid transient 504 Outdated
  // Optimize Dep responses on the public tunnel.
  optimizeDeps: {
    include: [
      "@blueprintjs/core",
      "@tanstack/react-table",
      "@tanstack/react-virtual",
      "@xyflow/react",
      "echarts",
      "echarts-for-react",
      "lucide-react",
      "react-grid-layout",
    ],
  },
  server: {
    host: "127.0.0.1",
    port: 3100,
    strictPort: true,
    allowedHosts: ["kosa165.iptime.org"],
    proxy: apiProxy,
  },
  preview: {
    host: "127.0.0.1",
    port: 3100,
    strictPort: true,
    allowedHosts: ["kosa165.iptime.org"],
    proxy: apiProxy,
  },
  test: { environment: "jsdom", include: ["src/**/*.test.ts", "src/**/*.test.tsx", "src/standalone/**/*.test.js"] },
});
