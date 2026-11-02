import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

const rootDir = fileURLToPath(new URL("../..", import.meta.url));

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, rootDir, "");
  return {
    envDir: rootDir,
    plugins: [react()],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      port: Number(env.VITE_DEV_PORT ?? process.env.VITE_DEV_PORT ?? 5729),
      host: true,
      proxy: {
        "/api": {
          target: env.VITE_API_PROXY ?? process.env.VITE_API_PROXY ?? "http://localhost:5706",
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: "dist",
      sourcemap: false,
    },
  };
});
