/// <reference types="vite/client" />
declare global {
  interface Window {
    obsidience?: {
      synthesize: (text: string, voice?: string) => Promise<ArrayBuffer>;
      cancelSynthesis: () => Promise<void>;
      openLocalTerminal: (options: {
        cols: number;
        rows: number;
        onData: (data: string) => void;
        onExit: (payload: { sessionId: string; exitCode: number; signal?: number }) => void;
      }) => Promise<{
        sessionId: string;
        label: string;
        linkedSession: string;
        windowCols: number;
        windowRows: number;
        pid: number;
        write: (data: string) => void;
        resize: (size: { cols: number; rows: number }) => void;
        close: () => void;
      }>;
      platform: string;
    };
  }
}
export {};
