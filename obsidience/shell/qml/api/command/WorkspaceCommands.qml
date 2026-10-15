pragma ComponentBehavior: Bound

import QtQml

// Workspace settings on obsidience.shell.v1: pane grid, tile resize limit, OLED
// motion and per-Surface tiling, persisted by SurfaceLayout.
QtObject {
    id: root

    required property var server
    readonly property string eventSchema: server.eventSchema
    readonly property var surfaceLayout: server.surfaceLayout

    function workspaceState() {
        return {
            "schema": eventSchema,
            "type": "workspace.state",
            "revision": surfaceLayout.revision,
            "pane_grid_size": surfaceLayout.paneGridSize,
            "minimum_pane_grid_size": surfaceLayout.minimumPaneGridSize,
            "maximum_pane_grid_size": surfaceLayout.maximumPaneGridSize,
            "minimum_tile_count": surfaceLayout.minimumTileCount,
            "maximum_tile_count": surfaceLayout.maximumTileCount,
            "workspace_tile_gap": surfaceLayout.workspaceTileGap,
            "tile_resize_limit_percent": surfaceLayout.tileResizeLimitPercent,
            "minimum_tile_resize_limit_percent": surfaceLayout.minimumTileResizeLimitPercent,
            "maximum_tile_resize_limit_percent": surfaceLayout.maximumTileResizeLimitPercent,
            "oled_mode_enabled": surfaceLayout.oledModeEnabled,
            "oled_shift_distance_px": surfaceLayout.oledShiftDistancePx,
            "minimum_oled_shift_distance_px": surfaceLayout.minimumOledShiftDistancePx,
            "maximum_oled_shift_distance_px": surfaceLayout.maximumOledShiftDistancePx,
            "oled_travel_duration_seconds": surfaceLayout.oledTravelDurationSeconds,
            "minimum_oled_travel_duration_seconds": surfaceLayout.minimumOledTravelDurationSeconds,
            "maximum_oled_travel_duration_seconds": surfaceLayout.maximumOledTravelDurationSeconds,
            "oled_glow_rotation_hours": surfaceLayout.oledGlowRotationHours,
            "session_locked": server.sessionLocked,
            "lock_generation": server.lockGeneration,
            "minimum_oled_glow_rotation_hours": surfaceLayout.minimumOledGlowRotationHours,
            "maximum_oled_glow_rotation_hours": surfaceLayout.maximumOledGlowRotationHours,
            "workspace_tiling": surfaceLayout.workspaceTilingState()
        }
    }

    function handleWorkspaceCommand(command) {
        if (command.type === "workspace.state.request") {
            server.broadcast(workspaceState())
            return true
        }
        if (command.type === "workspace.grid.set") {
            if (surfaceLayout.commitPaneGridSize(command.pane_grid_size)) {
                server.broadcast(workspaceState())
            }
            return true
        }
        if (command.type === "workspace.tile.limit.set") {
            if (surfaceLayout.commitTileResizeLimitPercent(
                    command.tile_resize_limit_percent
            )) {
                server.broadcast(workspaceState())
            }
            return true
        }
        if (command.type === "workspace.oled.set") {
            if (surfaceLayout.commitOledSettings(
                    command.oled_mode_enabled,
                    command.oled_shift_distance_px,
                    command.oled_travel_duration_seconds,
                    command.oled_glow_rotation_hours
            )) {
                server.broadcast(workspaceState())
            }
            return true
        }
        if (command.type === "workspace.tiling.set") {
            if (surfaceLayout.commitWorkspaceTiling(
                    command.surface_id,
                    command.columns,
                    command.rows
            )) {
                server.broadcast(workspaceState())
            }
            return true
        }
        return false
    }

    property Connections surfaceLayoutConnections: Connections {
        target: root.surfaceLayout
        function onPaneGridSizeChanged() {
            root.server.broadcast(root.workspaceState())
        }
    }
}
