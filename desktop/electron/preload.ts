import { contextBridge, ipcRenderer, type IpcRendererEvent } from "electron";
import type { LocalBotState, LocalSetup } from "../shared/localBot";
import type { ApiCall, ConnectionInput, DesktopBridge, WsEvent, WsState } from "../shared/types";

const bridge: DesktopBridge = {
  getConfig: () => ipcRenderer.invoke("config:get"),
  saveConfig: (input: ConnectionInput) => ipcRenderer.invoke("config:save", input),
  call: (call: ApiCall) => ipcRenderer.invoke("api:call", call),
  getWsState: () => ipcRenderer.invoke("ws:state"),
  onEvent(listener: (event: WsEvent) => void) {
    const handler = (_e: IpcRendererEvent, ev: WsEvent) => listener(ev);
    ipcRenderer.on("ws:event", handler);
    return () => ipcRenderer.removeListener("ws:event", handler);
  },
  onWsState(listener: (state: WsState) => void) {
    const handler = (_e: IpcRendererEvent, s: WsState) => listener(s);
    ipcRenderer.on("ws:state", handler);
    return () => ipcRenderer.removeListener("ws:state", handler);
  },
  localBot: {
    getState: () => ipcRenderer.invoke("localBot:state"),
    getSetup: () => ipcRenderer.invoke("localBot:getSetup"),
    saveSetup: (setup: LocalSetup) => ipcRenderer.invoke("localBot:saveSetup", setup),
    start: () => ipcRenderer.invoke("localBot:start"),
    stop: () => ipcRenderer.invoke("localBot:stop"),
    onState(listener: (state: LocalBotState) => void) {
      const handler = (_e: IpcRendererEvent, s: LocalBotState) => listener(s);
      ipcRenderer.on("localBot:state", handler);
      return () => ipcRenderer.removeListener("localBot:state", handler);
    },
  },
};

contextBridge.exposeInMainWorld("desktop", bridge);
