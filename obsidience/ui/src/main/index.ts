import { app, BrowserWindow, shell } from "electron";
import { join } from "path";

let win: BrowserWindow | null = null;

function installCameraPermissionPolicy(window: BrowserWindow): void {
  const ownerId = window.webContents.id;
  const mediaSession = window.webContents.session;
  mediaSession.setPermissionCheckHandler((webContents, permission, _origin, details) =>
    permission === "media"
      && webContents?.id === ownerId
      && details.isMainFrame
      && details.mediaType !== "audio");
  mediaSession.setPermissionRequestHandler((webContents, permission, callback, details) => {
    const mediaTypes = permission === "media" ? details.mediaTypes : undefined;
    callback(
      webContents.id === ownerId
        && permission === "media"
        && details.isMainFrame
        && mediaTypes?.length === 1
        && mediaTypes[0] === "video",
    );
  });
}

function createWindow(): void {
  win = new BrowserWindow({
    width: 1720,
    height: 1040,
    fullscreen: true,
    show: false,
    backgroundColor: "#02060c",
    autoHideMenuBar: true,
    title: "Obsidience",
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      sandbox: false,
    },
  });
  installCameraPermissionPolicy(win);
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
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
