import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` → http://localhost:5173 con /api proxyado a FastAPI (python -m web).
// `npm run build` → estáticos en web/static, que FastAPI sirve en http://127.0.0.1:8000.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../static", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
