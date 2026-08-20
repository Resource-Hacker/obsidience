/// <reference types="vite/client" />
declare global {
  interface Window {
    obsidience?: {
      synthesize: (text: string, voice?: string) => Promise<ArrayBuffer>;
      cancelSynthesis: () => Promise<void>;
      platform: string;
    };
  }
}
export {};
