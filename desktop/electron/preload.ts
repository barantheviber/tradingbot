import { contextBridge, ipcRenderer, type IpcRendererEvent } from "electron";
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
};

contextBridge.exposeInMainWorld("desktop", bridge);
