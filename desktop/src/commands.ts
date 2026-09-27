import type { Command } from "../shared/types";
import { api } from "./api";

const FOLLOW_EVERY_MS = 2_000;
const FOLLOW_FOR_MS = 90_000;

/** Waits until the bot has handled a queued command; null if it has not within FOLLOW_FOR_MS. */
export async function followCommand(id: number): Promise<Command | null> {
  const until = Date.now() + FOLLOW_FOR_MS;
  while (Date.now() < until) {
    await new Promise((r) => setTimeout(r, FOLLOW_EVERY_MS));
    try {
      const cmd = await api.command(id);
      if (cmd.status !== "pending") return cmd;
    } catch {
      // keep trying until the deadline; the status bar reports connection problems
    }
  }
  return null;
}
