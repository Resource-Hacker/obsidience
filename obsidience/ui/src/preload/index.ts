import { randomUUID } from "node:crypto";
import { contextBridge, ipcRenderer, type IpcRendererEvent } from "electron";

interface TerminalSize { cols: number; rows: number }
interface TerminalExit { sessionId: string; exitCode: number; signal?: number }
interface TerminalOpenOptions extends TerminalSize {
  onData: (data: string) => void;
  onExit: (payload: TerminalExit) => void;
}
interface TerminalHandle {
  sessionId: string;
  label: string;
  linkedSession: string;
  windowCols: number;
  windowRows: number;
  pid: number;
  write: (data: string) => void;
  resize: (size: TerminalSize) => void;
  close: () => void;
}

const terminalChannel = {
  data: (id: string) => `terminal:local:data:${id}`,
  exit: (id: string) => `terminal:local:exit:${id}`,
};

const configuredSurfaceId = process.env.OBSIDIENCE_SURFACE_ID?.trim() ?? "";
const surfaceId = /^[a-z0-9][a-z0-9-]{0,63}$/.test(configuredSurfaceId)
  ? configuredSurfaceId
  : "usb-c";

contextBridge.exposeInMainWorld("obsidience", {
  async openLocalTerminal({ cols, rows, onData, onExit }: TerminalOpenOptions): Promise<TerminalHandle> {
    const sessionId = randomUUID();
    const dataChannel = terminalChannel.data(sessionId);
    const exitChannel = terminalChannel.exit(sessionId);
    let closed = false;
    const dataListener = (_event: IpcRendererEvent, data: string) => {
      if (!closed && typeof data === "string") onData(data);
    };
    const cleanup = () => {
      ipcRenderer.removeListener(dataChannel, dataListener);
      ipcRenderer.removeListener(exitChannel, exitListener);
    };
    const exitListener = (_event: IpcRendererEvent, payload: TerminalExit) => {
      if (closed) return;
      closed = true;
      cleanup();
      onExit(payload);
    };
    ipcRenderer.on(dataChannel, dataListener);
    ipcRenderer.once(exitChannel, exitListener);
    try {
      const opened = await ipcRenderer.invoke("terminal:local:open", { sessionId, cols, rows });
      return {
        ...opened,
        write(data: string) {
          if (!closed) ipcRenderer.send("terminal:local:write", sessionId, data);
        },
        resize(size: TerminalSize) {
          if (!closed) ipcRenderer.send("terminal:local:resize", sessionId, size);
        },
        close() {
          if (closed) return;
          closed = true;
          cleanup();
          ipcRenderer.send("terminal:local:close", sessionId);
        },
      } as TerminalHandle;
    } catch (error) {
      closed = true;
      cleanup();
      throw error;
    }
  },
  platform: process.platform,
  surfaceId,
});
