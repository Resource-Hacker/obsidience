import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("obsidience", {
  synthesize: (text: string, voice?: string): Promise<ArrayBuffer> =>
    ipcRenderer.invoke("tts:synthesize", text, voice),
  cancelSynthesis: (): Promise<void> => ipcRenderer.invoke("tts:cancel"),
  platform: process.platform,
});
