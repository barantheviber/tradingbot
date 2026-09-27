import WebSocket from "ws";
import type { WsEvent, WsState } from "../shared/types";
import { wsUrl } from "./apiRoutes";

/** Keeps one WebSocket to /api/ws open, reconnecting with capped exponential backoff + jitter. */
export class LiveFeed {
  private socket: WebSocket | null = null;
  private timer: NodeJS.Timeout | null = null;
  private attempt = 0;
  private stopped = true;

  constructor(
    private readonly onEvent: (event: WsEvent) => void,
    private readonly onState: (state: WsState) => void,
  ) {}

  start(baseUrl: string, token: string): void {
    this.stop();
    this.stopped = false;
    this.attempt = 0;
    this.connect(baseUrl, token);
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.socket) {
      this.socket.removeAllListeners();
      this.socket.on("error", () => undefined);
      this.socket.terminate();
    }
    this.socket = null;
    this.onState("closed");
  }

  private connect(baseUrl: string, token: string): void {
    this.onState("connecting");
    const socket = new WebSocket(wsUrl(baseUrl, token), { handshakeTimeout: 10_000 });
    this.socket = socket;
    socket.on("open", () => {
      this.attempt = 0;
      this.onState("open");
    });
    socket.on("message", (raw) => {
      try {
        const msg = JSON.parse(raw.toString()) as WsEvent;
        if (msg && (msg.type === "status" || msg.type === "positions" || msg.type === "log")) this.onEvent(msg);
      } catch {
        // ignore malformed frames
      }
    });
    socket.on("error", () => undefined); // "close" follows and handles reconnect
    socket.on("close", () => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.onState("closed");
      if (this.stopped) return;
      const delay = Math.min(30_000, 1000 * 2 ** this.attempt) * (0.5 + Math.random() / 2);
      this.attempt += 1;
      this.timer = setTimeout(() => this.connect(baseUrl, token), delay);
    });
  }
}
