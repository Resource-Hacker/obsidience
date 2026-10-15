// Obsidience Cast on YouTube: a "Cast to TV" button in the player controls.
// It sends this page's video id and the local position to the extension worker (the native host
// casts it to the registered TV) and pauses the local video only when the TV reports playback.
// YouTube is a single-page app, so the button is put back after each navigation.
(() => {
  "use strict";
  if (window.__obsidienceCast) return;
  window.__obsidienceCast = true;

  const BUTTON = "obsidience-cast-button";
  let casting = false;

  function videoId() {
    const url = new URL(location.href);
    const id = url.pathname === "/watch" ? url.searchParams.get("v") : null;
    return /^[A-Za-z0-9_-]{11}$/.test(id || "") ? id : null;
  }

  function player() {
    return document.querySelector("#movie_player") || document.querySelector(".html5-video-player");
  }

  function toast(text) {
    document.getElementById("obsidience-cast-toast")?.remove();
    const note = document.createElement("div");
    note.id = "obsidience-cast-toast";
    note.textContent = text;
    Object.assign(note.style, {
      position: "fixed", left: "50%", bottom: "72px", transform: "translateX(-50%)", zIndex: 2147483647,
      maxWidth: "min(560px, calc(100vw - 32px))", padding: "10px 16px", borderRadius: "8px",
      background: "rgba(28, 28, 28, 0.92)", color: "#fff", font: "14px/1.4 Roboto, Arial, sans-serif",
      boxShadow: "0 2px 12px rgba(0, 0, 0, 0.4)", pointerEvents: "none",
    });
    document.body.appendChild(note);
    setTimeout(() => note.remove(), 5000);
  }

  async function cast() {
    if (casting) return;
    const id = videoId();
    if (!id) { toast("No YouTube video on this page."); return; }
    const root = player();
    const video = root?.querySelector("video") || document.querySelector("video");
    const message = { type: "obsidience-cast", videoId: id };
    // A live stream has no start position to carry.
    if (video && isFinite(video.currentTime) && !root?.classList.contains("ytp-live")) {
      const start = Math.floor(video.currentTime);
      if (start > 0 && start <= 86400) message.start = start;
    }
    casting = true;
    toast("Casting to TV…");
    try {
      const reply = await chrome.runtime.sendMessage(message);
      if (reply && reply.ok === true && reply.state === "completed") {
        video?.pause();
        toast(reply.summary || "Playing on the TV.");
      } else {
        toast((reply && reply.summary) || "The cast did not complete.");
      }
    } catch (error) {
      toast("No answer from the cast host. The cast was not resent.");
    } finally {
      casting = false;
    }
  }

  function icon() {
    // Built as DOM nodes: YouTube enforces Trusted Types, which rejects HTML strings.
    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", "0 0 36 36");
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "100%");
    const path = document.createElementNS(svgNS, "path");
    path.setAttribute("fill", "#fff");
    path.setAttribute("d", "M9 11h18a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V13a2 2 0 0 1 2-2zm0 2v10h18V13H9z"
      + "m5 14h8v2h-8z");
    svg.appendChild(path);
    return svg;
  }

  function addButton() {
    const controls = document.querySelector(".ytp-right-controls");
    if (!controls) return false;
    if (controls.querySelector("." + BUTTON)) return true;
    const button = document.createElement("button");
    button.className = "ytp-button " + BUTTON;
    button.title = "Cast to TV";
    button.setAttribute("aria-label", "Cast to TV");
    button.appendChild(icon());
    button.addEventListener("click", event => { event.stopPropagation(); cast(); });
    controls.prepend(button);
    return true;
  }

  function ensureButton(attempts = 20) {
    if (!videoId() || addButton() || attempts <= 0) return;
    setTimeout(() => ensureButton(attempts - 1), 500);
  }

  document.addEventListener("yt-navigate-finish", () => ensureButton());
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "obsidience-cast-click") return;
    sendResponse({ accepted: true });  // The toolbar click reached this page; the toast reports the cast.
    cast();
  });
  ensureButton();
})();
