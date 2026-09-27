import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Renderer bundle. base "./" so the built index.html loads from file:// inside Electron.
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { port: 5173, strictPort: true },
  build: { outDir: "dist", emptyOutDir: true },
});
