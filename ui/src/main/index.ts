import { app, BrowserWindow, ipcMain, shell } from "electron";
import { join } from "path";
import {
  cancelPendingKokoroSpeech,
  preloadKokoroSpeech,
  synthesizeKokoroSpeech,
  type KokoroVoice,
} from "./tts/kokoro";

let win: BrowserWindow | null = null;

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
