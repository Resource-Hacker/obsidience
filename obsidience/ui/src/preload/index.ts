import { contextBridge } from "electron";

const configuredSurfaceId = process.env.OBSIDIENCE_SURFACE_ID?.trim() ?? "";
const surfaceId = /^[a-z0-9][a-z0-9-]{0,63}$/.test(configuredSurfaceId)
  ? configuredSurfaceId
  : "usb-c";

contextBridge.exposeInMainWorld("obsidience", {
  platform: process.platform,
  surfaceId,
});
