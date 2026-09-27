import { app, BrowserWindow, ipcMain, shell } from "electron";
import path from "node:path";
import type { ApiCall, ConnectionInput, WsState } from "../shared/types";
import { performCall } from "./apiClient";
import { normaliseBaseUrl } from "./apiRoutes";
import { getPublicConfig, getToken, saveConfig } from "./configStore";
import { LiveFeed } from "./wsClient";

let win: BrowserWindow | null = null;
let wsState: WsState = "closed";

const feed = new LiveFeed(
  (event) => win?.webContents.send("ws:event", event),
  (state) => {
    wsState = state;
    win?.webContents.send("ws:state", state);
  },
);

function restartFeed(): void {
  const { baseUrl } = getPublicConfig();
  const token = getToken();
  if (token) feed.start(baseUrl, token);
  else feed.stop();
}

function createWindow(): void {
  win = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 640,
    backgroundColor: "#0f1115",
    title: "Trading Bot",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  // External links open in the system browser; the app itself never navigates away.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e) => e.preventDefault());

  const devUrl = process.env.VITE_DEV_SERVER_URL;
  if (devUrl) void win.loadURL(devUrl);
  else void win.loadFile(path.join(__dirname, "..", "..", "dist", "index.html"));
  win.on("closed", () => {
    win = null;
  });
}

ipcMain.handle("config:get", () => getPublicConfig());

// The renderer asks on mount: pushes sent before its listener existed would be lost.
ipcMain.handle("ws:state", () => wsState);

ipcMain.handle("config:save", (_e, input: ConnectionInput) => {
  const cfg = saveConfig(normaliseBaseUrl(String(input.baseUrl ?? "")), input.token);
  restartFeed();
  return cfg;
});

ipcMain.handle("api:call", (_e, call: ApiCall) => {
  const { baseUrl } = getPublicConfig();
  return performCall(baseUrl, getToken(), call);
});

app.whenReady().then(() => {
  createWindow();
  restartFeed();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  feed.stop();
  if (process.platform !== "darwin") app.quit();
});
