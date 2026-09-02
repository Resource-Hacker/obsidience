const COOLDOWN_MS = 120;
const EDGE_PIXELS = 2;
const REARM_PIXELS = 4;

let bottomArmed = false;

const lastTrigger = {
    left: 0,
    right: 0,
    top: 0,
    bottom: 0,
};

function numberFrom(value, fallback) {
    if (value === undefined || value === null) {
        return fallback;
    }
    return Number(value);
}

function geometry() {
    const geo = workspace.virtualScreenGeometry;
    return {
        x: numberFrom(geo.x, 0),
        y: numberFrom(geo.y, 0),
        width: numberFrom(geo.width, 5120),
        height: numberFrom(geo.height, 1440),
    };
}

function enterMapped(edge) {
    const now = Date.now();
    if (now - lastTrigger[edge] < COOLDOWN_MS) {
        return;
    }

    const pos = workspace.cursorPos;
    const geo = geometry();
    const localX = Math.max(0, Math.min(geo.width - 1, Math.round(numberFrom(pos.x, 0) - geo.x)));
    const localY = Math.max(0, Math.min(geo.height - 1, Math.round(numberFrom(pos.y, 0) - geo.y)));
    lastTrigger[edge] = now;

    callDBus(
        "org.wissenschafter.DP4Bridge",
        "/org/wissenschafter/DP4Bridge",
        "org.wissenschafter.DP4Bridge",
        "EnterMapped",
        edge,
        String(localX),
        String(localY)
    );
}

function enterFromBottomEdge() {
    bottomArmed = false;
    enterMapped("bottom");
}

function trackBottomEdge() {
    const pos = workspace.cursorPos;
    const geo = geometry();
    const localY = numberFrom(pos.y, 0) - geo.y;

    if (localY < geo.height - EDGE_PIXELS - REARM_PIXELS) {
        bottomArmed = true;
        return;
    }
    if (bottomArmed && localY >= geo.height - EDGE_PIXELS) {
        enterFromBottomEdge();
    }
}

function reportFullscreen() {
    let active = false;
    for (const window of workspace.windowList()) {
        if (window.fullScreen && window.output && window.output.name === "HDMI-A-1") {
            active = true;
            break;
        }
    }
    callDBus(
        "org.wissenschafter.DP4Bridge",
        "/org/wissenschafter/DP4Bridge",
        "org.wissenschafter.DP4Bridge",
        "ReportFullscreen",
        active ? "1" : "0"
    );
}

function watchFullscreen(window) {
    if (!window) return;
    if (window.fullScreenChanged) window.fullScreenChanged.connect(reportFullscreen);
    if (window.outputChanged) window.outputChanged.connect(reportFullscreen);
}

function moveActivePane(direction) {
    callDBus(
        "org.wissenschafter.DP4Bridge",
        "/org/wissenschafter/DP4Bridge",
        "org.wissenschafter.DP4Bridge",
        "MovePane",
        "samsung",
        direction
    );
}

registerShortcut(
    "ObsidiencePaneLeft",
    "Move active Obsidience pane to the left Surface",
    "Meta+Shift+Left",
    () => moveActivePane("left")
);
registerShortcut(
    "ObsidiencePaneRight",
    "Move active Obsidience pane to the right Surface",
    "Meta+Shift+Right",
    () => moveActivePane("right")
);
registerShortcut(
    "ObsidiencePaneUp",
    "Move active Obsidience pane to the upper Surface",
    "Meta+Shift+Up",
    () => moveActivePane("top")
);
registerShortcut(
    "ObsidiencePaneDown",
    "Move active Obsidience pane to the lower Surface",
    "Meta+Shift+Down",
    () => moveActivePane("bottom")
);

const edgeRegistered = registerScreenEdge(KWin.ElectricBottom, enterFromBottomEdge);
assert(edgeRegistered, "Failed to register the Obsidience bottom Surface edge");
workspace.cursorPosChanged.connect(trackBottomEdge);
workspace.windowAdded.connect((window) => {
    watchFullscreen(window);
    reportFullscreen();
});
workspace.windowRemoved.connect(reportFullscreen);

for (const window of workspace.windowList()) watchFullscreen(window);
reportFullscreen();

callDBus(
    "org.wissenschafter.DP4Bridge",
    "/org/wissenschafter/DP4Bridge",
    "org.wissenschafter.DP4Bridge",
    "AdapterReady",
    "ready"
);
