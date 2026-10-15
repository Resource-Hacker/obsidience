// Obsidience Cast: the only path to the native host org.obsidience.edge.
// The content script on YouTube reports one video id and position; this worker builds the closed
// cast message and returns the host's {ok, state, summary}. Each click is one cast, never resent.
"use strict";

const HOST = "org.obsidience.edge";
const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;
const YOUTUBE = "https://www.youtube.com/";

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== "obsidience-cast" || sender.id !== chrome.runtime.id
      || !sender.tab || !String(sender.url || "").startsWith(YOUTUBE)) return false;
  if (!VIDEO_ID.test(String(message.videoId))) {
    sendResponse({ ok: false, state: "rejected", summary: "No YouTube video on this page." });
    return false;
  }
  const cast = { type: "cast", url: "https://www.youtube.com/watch?v=" + message.videoId };
  if (Number.isInteger(message.start) && message.start > 0 && message.start <= 86400) cast.start = message.start;
  chrome.runtime.sendNativeMessage(HOST, cast).then(
    reply => sendResponse(reply && typeof reply.ok === "boolean" ? reply
      : { ok: false, state: "failed", summary: "The cast host gave no answer. The cast was not resent." }),
    error => sendResponse({ ok: false, state: "unavailable",
                            summary: "The cast host is unavailable: " + (error && error.message || error) }));
  return true;  // sendResponse is called after the host settles.
});

function refuse(tabId) {
  // Shown briefly on the toolbar button: there is no YouTube page here to cast from.
  chrome.action.setBadgeText({ tabId, text: "!" });
  setTimeout(() => chrome.action.setBadgeText({ tabId, text: "" }), 4000);
}

// The toolbar button casts the active tab's video through the same content script.
chrome.action.onClicked.addListener(async tab => {
  if (!tab.id) return;
  if (!String(tab.url || "").startsWith(YOUTUBE)) { refuse(tab.id); return; }
  const request = { type: "obsidience-cast-click" };
  try {
    await chrome.tabs.sendMessage(tab.id, request);
  } catch (missing) {
    // The tab was open before the extension loaded: add its content script once, then ask again.
    try {
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
      await chrome.tabs.sendMessage(tab.id, request);
    } catch (error) {
      refuse(tab.id);
    }
  }
});
