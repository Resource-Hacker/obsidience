/*
 * Read-only KWin observer adapted from Noctalia v5.0.0-beta.10.
 * Copyright (c) 2026 noctalia-dev. Distributed under the MIT License.
 * The KWin adapter removes every mutation path and uses its own D-Bus namespace.
 */

const BUS = "org.obsidience.Shell.WindowObserver";
const PATH = "/org/obsidience/Shell/WindowObserver";
const IFACE = "org.obsidience.Shell.WindowObserver";
const RECORD_SEPARATOR = "\x1f";
const FIELD_SEPARATOR = "\x1e";

function windowId(window) {
  if (!window || window.internalId === undefined) return "";
  return String(window.internalId);
}

function isShellSurface(window) {
  if (!window) return false;
  const appId = (window.resourceClass || "").toLowerCase();
  return appId === "obsidience-shell" || appId === "org.obsidience.shell";
}

function shouldTrack(window) {
  return Boolean(
    window
      && !window.skipTaskbar
      && !window.dock
      && !window.desktopWindow
      && !window.tooltip
      && !window.notification
      && window.normalWindow
      && !window.dialog
      && !window.splash
      && !window.utility
      && !window.dropdownMenu
      && !window.popupMenu
      && !isShellSurface(window)
  );
}

function desktopIds(window) {
  if (!window) return "";
  if (window.onAllDesktops) return "*";
  if (!window.desktops) return "";
  return window.desktops.map((desktop) => String(desktop.id || "")).filter(Boolean).join(",");
}

function outputName(window) {
  return window && window.output ? (window.output.name || "") : "";
}

function notifyActive(window) {
  try {
    if (!window || !shouldTrack(window)) {
      callDBus(BUS, PATH, IFACE, "NotifyActiveWindow", "", "", "");
      return;
    }
    callDBus(
      BUS,
      PATH,
      IFACE,
      "NotifyActiveWindow",
      window.caption || "",
      window.resourceClass || "",
      windowId(window)
    );
  } catch (error) {
    print("obsidience-shell observer notify failed: " + error);
  }
}

function serialize(window) {
  if (!shouldTrack(window)) return "";
  const id = windowId(window);
  if (!id) return "";
  return [
    id,
    window.resourceClass || "",
    window.caption || "",
    desktopIds(window),
    outputName(window),
  ].join(FIELD_SEPARATOR);
}

function syncWindows() {
  try {
    const rows = [];
    for (const window of workspace.windowList()) {
      const row = serialize(window);
      if (row) rows.push(row);
    }
    callDBus(BUS, PATH, IFACE, "NotifyWindowList", rows.join(RECORD_SEPARATOR));
  } catch (error) {
    print("obsidience-shell observer sync failed: " + error);
  }
}

function wire(window) {
  if (!window) return;
  const updateActive = () => {
    if (workspace.activeWindow === window) notifyActive(window);
  };
  if (window.captionChanged) window.captionChanged.connect(updateActive);
  if (window.captionChanged) window.captionChanged.connect(syncWindows);
  if (window.desktopsChanged) window.desktopsChanged.connect(syncWindows);
  if (window.outputChanged) window.outputChanged.connect(syncWindows);
}

workspace.windowActivated.connect(notifyActive);
workspace.windowAdded.connect((window) => {
  wire(window);
  syncWindows();
});
workspace.windowRemoved.connect(syncWindows);

for (const window of workspace.windowList()) wire(window);
notifyActive(workspace.activeWindow);
syncWindows();
