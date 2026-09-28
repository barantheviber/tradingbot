import { app, BrowserWindow, dialog, ipcMain, Menu, shell } from "electron";
import path from "node:path";
import type { LocalBotState, LocalSetup } from "../shared/localBot";
import type { ApiCall, ConnectionInput, Position, WsState } from "../shared/types";
import { performCall } from "./apiClient";
import { normaliseBaseUrl } from "./apiRoutes";
import { getPublicConfig, getToken, saveConfig } from "./configStore";
import { dataDir, LOCAL_BASE_URL, LocalBot } from "./localBot";
import { LiveFeed } from "./wsClient";

let win: BrowserWindow | null = null;
let wsState: WsState = "closed";
let quitting = false;

// With TRADINGBOT_API_URL set (development against `python -m api.demo`) the app only connects;
// otherwise it runs the bundled bot on this computer and talks to it on 127.0.0.1.
const managed = !process.env.TRADINGBOT_API_URL;

// Turkish for Chromium's own texts (context menus, form validation) and no English menu bar.
app.commandLine.appendSwitch("lang", "tr");

const feed = new LiveFeed(
  (event) => win?.webContents.send("ws:event", event),
  (state) => {
    wsState = state;
    win?.webContents.send("ws:state", state);
  },
);

const localBot = new LocalBot((state) => {
  win?.webContents.send("localBot:state", state);
  if (state.phase === "running") restartFeed();
});

function localState(): LocalBotState {
  return managed ? localBot.state() : { managed: false, setupDone: true, phase: "stopped", message: null };
}

function restartFeed(): void {
  const { baseUrl } = getPublicConfig();
  const token = getToken();
  if (token) feed.start(baseUrl, token);
  else feed.stop();
}

async function openPositions(): Promise<Position[] | null> {
  const res = await performCall<{ positions: Position[] }>(getPublicConfig().baseUrl, getToken(), { kind: "positions" });
  return res.ok ? res.data.positions : null;
}

/** Closing the window stops the bot: say so first, and warn about open positions. */
async function confirmClose(): Promise<boolean> {
  if (!managed || !localBot.isRunning || !win) return true;
  const positions = await openPositions();
  const count = positions?.length ?? 0;
  const detail =
    count > 0
      ? `${count} açık pozisyon var. Bot durunca bu pozisyonların stop-loss, kâr al ve trailing takibi de durur. ` +
        "Bot bu bilgisayarda tekrar açılınca kaldığı yerden devam eder, ama telefon bu pozisyonları bilmez.\n\n" +
        "Cihaz değiştirecekseniz önce Genel bakış'taki \"Durdur\" ile pozisyonları kapatıp botu durdurun."
      : "Uygulama kapanınca bot da durur.";
  const { response } = await dialog.showMessageBox(win, {
    type: count > 0 ? "warning" : "question",
    buttons: ["Vazgeç", count > 0 ? "Yine de kapat" : "Botu durdur ve kapat"],
    defaultId: 0,
    cancelId: 0,
    title: "Trading Bot",
    message: count > 0 ? "Açık pozisyonlar var" : "Bot çalışıyor",
    detail,
  });
  return response === 1;
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
  win.on("close", (e) => {
    if (quitting) return;
    e.preventDefault();
    void confirmClose().then((ok) => {
      if (ok) {
        quitting = true;
        app.quit();
      }
    });
  });
  win.on("closed", () => {
    win = null;
  });
}

ipcMain.handle("config:get", () => getPublicConfig());

// The renderer asks on mount: pushes sent before its listener existed would be lost.
ipcMain.handle("ws:state", () => wsState);

ipcMain.handle("config:save", (_e, input: ConnectionInput) => {
  if (managed) throw new Error("Bu bilgisayardaki bot kullanılıyor; bağlantı adresi değiştirilemez.");
  const cfg = saveConfig(normaliseBaseUrl(String(input.baseUrl ?? "")), input.token);
  restartFeed();
  return cfg;
});

ipcMain.handle("api:call", (_e, call: ApiCall) => {
  const { baseUrl } = getPublicConfig();
  return performCall(baseUrl, getToken(), call);
});

ipcMain.handle("localBot:state", () => localState());
ipcMain.handle("localBot:getSetup", () => (managed ? localBot.getSetup() : null));
ipcMain.handle("localBot:saveSetup", async (_e, setup: LocalSetup) => {
  if (!managed) throw new Error("Geliştirme modunda kurulum yok.");
  const state = await localBot.saveSetup(setup);
  restartFeed();
  return state;
});
ipcMain.handle("localBot:start", async () => {
  if (managed) await localBot.start();
  return localState();
});
ipcMain.handle("localBot:openLogFolder", async () => {
  if (managed) await shell.openPath(path.join(dataDir(), "logs"));
});
// Only the installed app registers itself; in development this would register the Electron binary.
const loginItemSupported = () => managed && app.isPackaged;
ipcMain.handle("localBot:getOpenAtLogin", () => ({
  supported: loginItemSupported(),
  enabled: loginItemSupported() && app.getLoginItemSettings().openAtLogin,
}));
ipcMain.handle("localBot:setOpenAtLogin", (_e, enabled: boolean) => {
  if (loginItemSupported()) app.setLoginItemSettings({ openAtLogin: Boolean(enabled) });
});
ipcMain.handle("localBot:stop", async () => {
  if (managed) await localBot.stop();
  return localState();
});

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  if (managed && localBot.getSetup()) saveConfig(LOCAL_BASE_URL);
  createWindow();
  restartFeed();
  if (managed) void localBot.resume();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

// Stop the bot gracefully before the app exits; autoStart stays set so it resumes next launch.
let stopped = false;
app.on("before-quit", (e) => {
  quitting = true;
  if (stopped || !managed || !localBot.isRunning) return;
  e.preventDefault();
  feed.stop();
  void localBot.stop({ remember: false }).finally(() => {
    stopped = true;
    app.quit();
  });
});

app.on("window-all-closed", () => {
  feed.stop();
  if (process.platform !== "darwin") app.quit();
});
