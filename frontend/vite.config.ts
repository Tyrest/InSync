import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const RUNTIME_BASE_PLACEHOLDER = "/__INSYNC_BASE__/";

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, ".", "");
  // Keep dev at root path, but use a stable placeholder for production
  // so backend can rewrite to runtime BASE_URL.
  const base = env.VITE_BASE_URL ?? (command === "build" ? RUNTIME_BASE_PLACEHOLDER : "/");
  return {
    base,
    plugins: [react()],
  };
});
