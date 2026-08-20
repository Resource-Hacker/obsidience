import { app, BrowserWindow, ipcMain, shell } from "electron";
import { join } from "path";
import {
  cancelPendingKokoroSpeech,
  preloadKokoroSpeech,
  synthesizeKokoroSpeech,
  type KokoroVoice,
} from "./tts/kokoro";
import { LocalTerminalManager } from "./terminal/local-terminal";

let win: BrowserWindow | null = null;
let localTerminalManager: LocalTerminalManager | null = null;

const TERMINAL_IPC = {
  open: "terminal:local:open",
  write: "terminal:local:write",
  resize: "terminal:local:resize",
  close: "terminal:local:close",
  data: (id: string) => `terminal:local:data:${id}`,
  exit: (id: string) => `terminal:local:exit:${id}`,
};

function createWindow(): void {
  win = new BrowserWindow({
    width: 1720,
    height: 1040,
    show: false,
    backgroundColor: "#02060c",
    autoHideMenuBar: true,
    title: "Obsidience",
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      sandbox: false,
    },
  });
  win.on("ready-to-show", () => win?.show());
  win.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: "deny" };
  });
  if (process.env.ELECTRON_RENDERER_URL) {
    void win.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    void win.loadFile(join(__dirname, "../renderer/index.html"));
  }
}

app.whenReady().then(() => {
  ipcMain.handle("tts:synthesize", async (_e, text: string, voice?: string) => {
    const wav = await synthesizeKokoroSpeech(String(text ?? ""), {
      voice: voice as KokoroVoice | undefined,
    });
    return wav;
  });
  ipcMain.handle("tts:cancel", () => cancelPendingKokoroSpeech());
  const terminals = new LocalTerminalManager({
    onData: (ownerId, sessionId, data) => {
      if (win && !win.isDestroyed() && win.webContents.id === ownerId) {
        win.webContents.send(TERMINAL_IPC.data(sessionId), data);
      }
    },
    onExit: (ownerId, payload) => {
      if (win && !win.isDestroyed() && win.webContents.id === ownerId) {
        win.webContents.send(TERMINAL_IPC.exit(payload.sessionId), payload);
      }
    },
  });
  localTerminalManager = terminals;
  ipcMain.handle(TERMINAL_IPC.open, (event, payload: unknown) => {
    if (!win || event.sender.id !== win.webContents.id) {
      throw new Error("The local terminal is available only in the main interface.");
    }
    const ownerId = event.sender.id;
    event.sender.once("destroyed", () => terminals.closeOwner(ownerId));
    return terminals.open(ownerId, payload);
  });
  ipcMain.on(TERMINAL_IPC.write, (event, sessionId: unknown, data: unknown) => {
    if (!win || event.sender.id !== win.webContents.id) return;
    try { terminals.write(event.sender.id, sessionId, data); } catch { /* stale input */ }
  });
  ipcMain.on(TERMINAL_IPC.resize, (event, sessionId: unknown, size: unknown) => {
    if (!win || event.sender.id !== win.webContents.id) return;
    try { terminals.resize(event.sender.id, sessionId, size); } catch { /* resize race */ }
  });
  ipcMain.on(TERMINAL_IPC.close, (event, sessionId: unknown) => {
    if (!win || event.sender.id !== win.webContents.id) return;
    try { terminals.close(event.sender.id, sessionId); } catch { /* idempotent close */ }
  });
  createWindow();
  // Warm the Kokoro model in the background so the first spoken reply is fast.
  preloadKokoroSpeech().catch((err) =>
    console.warn("[obsidience] kokoro preload failed:", err?.message ?? err),
  );
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  localTerminalManager?.dispose();
  localTerminalManager = null;
});
