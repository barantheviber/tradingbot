// Development runner: compiles the Electron main process, starts Vite, then launches
// Electron pointed at the dev server. Ctrl+C stops everything.
import { spawn, spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { createServer } from "vite";

const require = createRequire(import.meta.url);
const tsc = spawnSync(process.execPath, [require.resolve("typescript/bin/tsc"), "-p", "tsconfig.node.json"], {
  stdio: "inherit",
});
if (tsc.status !== 0) process.exit(tsc.status ?? 1);

const server = await createServer();
await server.listen();
const url = server.resolvedUrls?.local[0] ?? "http://localhost:5173/";
console.log(`Vite: ${url}`);

const electronPath = require("electron");
const child = spawn(electronPath, ["."], { stdio: "inherit", env: { ...process.env, VITE_DEV_SERVER_URL: url } });
child.on("exit", async (code) => {
  await server.close();
  process.exit(code ?? 0);
});
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => child.kill());
