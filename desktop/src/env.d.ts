import type { DesktopBridge } from "../shared/types";

declare global {
  interface Window {
    desktop: DesktopBridge;
  }
}

export {};
