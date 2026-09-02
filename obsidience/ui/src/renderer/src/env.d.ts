/// <reference types="vite/client" />
declare global {
  interface Window {
    obsidience?: {
      platform: string;
      surfaceId: string;
    };
  }
}
export {};
