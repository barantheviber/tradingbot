// Runs the bundled bot (bot + API in one process, see packaging/core_entry.py) on this
// computer: writes its .env from the setup screen, starts it, restarts it after a crash and
// stops it gracefully. The API it serves listens on 127.0.0.1 only.

import { app } from "electron";
import { spawn, type ChildProcess } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import type { LocalBotPhase, LocalBotState, LocalSetup } from "../shared/localBot";
import { validateSetup } from "../shared/localBot";
import { getToken, saveConfig } from "./configStore";
import {
  afterStart,
  afterStop,
  buildEnvFile,
  childEnv,
  exitReason,
  LOCAL_API_PORT,
  restartDelayMs,
  shouldResume,
  watchExit,
  type Stored,
} from "./localBotEnv";

const STOP_TIMEOUT_MS = 60_000;
const STABLE_AFTER_MS = 5 * 60_000;

export const LOCAL_BASE_URL = `http://127.0.0.1:${LOCAL_API_PORT}`;

function storeFile(): string {
  return path.join(app.getPath("userData"), "local-bot.json");
}

function readStored(): Stored {
  try {
    return JSON.parse(fs.readFileSync(storeFile(), "utf8")) as Stored;
  } catch {
    return {};
  }
}

function writeStored(s: Stored): void {
  fs.mkdirSync(path.dirname(storeFile()), { recursive: true });
  fs.writeFileSync(storeFile(), JSON.stringify(s, null, 2), "utf8");
}

export function dataDir(): string {
  return path.join(app.getPath("userData"), "bot");
}

function coreCommand(): { cmd: string; args: string[] } {
  if (app.isPackaged) {
    const exe = process.platform === "win32" ? "tradingbot-core.exe" : "tradingbot-core";
    return { cmd: path.join(process.resourcesPath, "core", exe), args: [] };
  }
  // Development: run the Python sources from the repository (requirements.txt installed).
  const repoRoot = path.resolve(__dirname, "..", "..", "..");
  const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
  return { cmd: python, args: [path.join(repoRoot, "packaging", "core_entry.py")] };
}

export class LocalBot {
  private child: ChildProcess | null = null;
  private phase: LocalBotPhase = "stopped";
  private message: string | null = null;
  private wantRunning = false;
  private crashes = 0;
  private restartTimer: NodeJS.Timeout | null = null;
  private exited: Promise<void> = Promise.resolve();

  constructor(private readonly onChange: (s: LocalBotState) => void) {}

  state(): LocalBotState {
    return { managed: true, setupDone: Boolean(readStored().setup), phase: this.phase, message: this.message };
  }

  getSetup(): LocalSetup | null {
    return readStored().setup ?? null;
  }

  get isRunning(): boolean {
    return this.child !== null;
  }

  /** Saves the setup; a running bot restarts so the new setup takes effect. */
  async saveSetup(setup: LocalSetup): Promise<LocalBotState> {
    const problems = validateSetup(setup);
    if (problems.length) throw new Error(problems.join(" "));
    const clean: LocalSetup = {
      exchangeId: setup.exchangeId,
      marketType: setup.marketType,
      symbols: [...setup.symbols],
      timeframe: setup.timeframe,
      startingBalance: Number(setup.startingBalance),
    };
    const firstSetup = !readStored().setup;
    writeStored({ ...readStored(), setup: clean });
    this.ensureToken();
    const wasRunning = this.isRunning;
    if (wasRunning) await this.stop({ remember: false });
    if (wasRunning || firstSetup) await this.start();
    return this.state();
  }

  /** Called on launch: starts the bot if it was running when the app closed. */
  async resume(): Promise<void> {
    if (shouldResume(readStored())) await this.start();
    else this.emit();
  }

  async start(): Promise<void> {
    const stored = readStored();
    if (!stored.setup) throw new Error("Önce kurulumu tamamlayın.");
    this.wantRunning = true;
    writeStored(afterStart(stored));
    this.crashes = 0;
    this.spawnChild();
  }

  /** remember=false keeps autoStart as it is (used for restarts and app shutdown). */
  async stop({ remember = true }: { remember?: boolean } = {}): Promise<void> {
    this.wantRunning = false;
    writeStored(afterStop(readStored(), remember));
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    const child = this.child;
    if (!child) {
      this.setPhase("stopped", null);
      return;
    }
    this.setPhase("stopping", null);
    // The core stops like on Ctrl+C when it reads "stop" or its stdin closes.
    try {
      child.stdin?.write("stop\n");
      child.stdin?.end();
    } catch {
      // already gone
    }
    const killTimer = setTimeout(() => child.kill(), STOP_TIMEOUT_MS);
    await this.exited;
    clearTimeout(killTimer);
  }

  private ensureToken(): void {
    if (getToken()) {
      saveConfig(LOCAL_BASE_URL);
      return;
    }
    saveConfig(LOCAL_BASE_URL, randomBytes(32).toString("base64url"));
  }

  private spawnChild(): void {
    if (this.child) return;
    const setup = readStored().setup;
    if (!setup) return;
    this.ensureToken();
    const dir = dataDir();
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, ".env"), buildEnvFile(setup), "utf8");

    const { cmd, args } = coreCommand();
    let outputTail = "";
    const startedAt = Date.now();
    this.setPhase("starting", null);
    const child = spawn(cmd, [...args, "run", "--data-dir", dir, "--stop-on-stdin-close"], {
      cwd: dir,
      env: childEnv(process.env, getToken()),
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    this.child = child;
    // Writing "stop" to a process that just died must not crash the app.
    child.stdin?.on("error", () => undefined);
    this.exited = watchExit(child, (code, startError) => {
      this.child = null;
      if (startError) this.onStartError(startError);
      else this.onExit(code, outputTail, Date.now() - startedAt);
    });
    // Logs go to stdout (the bot also writes them to logs/), errors to stderr. Both pipes must be
    // drained or the bot blocks once they fill up.
    for (const stream of [child.stdout, child.stderr]) {
      stream?.setEncoding("utf8");
      stream?.on("data", (chunk: string) => {
        outputTail = (outputTail + chunk).slice(-8_000);
        if (this.phase === "starting" && /Local runtime started/.test(chunk)) this.setPhase("running", null);
      });
    }
    // If the start line is missed, a process that is still alive counts as running.
    setTimeout(() => {
      if (this.child === child && this.phase === "starting") this.setPhase("running", null);
    }, 15_000);
  }

  private onExit(code: number | null, outputTail: string, uptimeMs: number): void {
    const reason = exitReason(outputTail);
    if (!this.wantRunning) {
      this.setPhase("stopped", null);
      return;
    }
    if (code === 2) {
      // configuration problem: restarting would fail the same way
      this.wantRunning = false;
      this.setPhase("error", reason ?? "Bot ayarlar yüzünden başlayamadı.");
      return;
    }
    if (uptimeMs > STABLE_AFTER_MS) this.crashes = 0;
    this.crashes += 1;
    const delay = restartDelayMs(this.crashes);
    this.setPhase("restarting", `${reason ?? "Bot beklenmedik şekilde durdu."} ${Math.round(delay / 1000)} sn sonra yeniden başlatılıyor.`);
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      if (this.wantRunning) this.spawnChild();
    }, delay);
  }

  /** The bot program could not be run at all; trying again would fail the same way. */
  private onStartError(err: Error): void {
    if (!this.wantRunning) {
      this.setPhase("stopped", null);
      return;
    }
    this.wantRunning = false;
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    this.setPhase(
      "error",
      `Bot programı çalıştırılamadı (${err.message}). Antivirüs programı engellemiş olabilir; ` +
        "uygulamayı yeniden kurmayı deneyin.",
    );
  }

  private setPhase(phase: LocalBotPhase, message: string | null): void {
    this.phase = phase;
    this.message = message;
    this.emit();
  }

  private emit(): void {
    this.onChange(this.state());
  }
}
