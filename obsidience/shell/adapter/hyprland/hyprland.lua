-- Obsidience's single-compositor Hyprland session.
-- Quickshell owns the visible shell; Hyprland owns composition and windows.

dofile("/home/wissenschafter/Projects/obsidience/obsidience/shell/adapter/hyprland/layout.lua")

hl.monitor({
    output = "HDMI-A-1",
    mode = "5120x1440@240",
    position = "0x0",
    scale = 1,
    bitdepth = 10,
    cm = "hdr",
    sdr_max_luminance = 225,
    vrr = 2,
})

hl.monitor({
    output = "HDMI-A-2",
    mode = "3840x1100@60",
    position = "0x1440",
    scale = 2,
    vrr = 0,
})

hl.monitor({
    output = "DP-8",
    mode = "3840x2400@60",
    position = "1920x1440",
    scale = 2,
    vrr = 0,
})

-- Keep each Surface's native workspace bound through output sleep and wake.
hl.workspace_rule({
    workspace = "1",
    monitor = "HDMI-A-1",
    persistent = true,
    default = true,
})

hl.workspace_rule({
    workspace = "2",
    monitor = "HDMI-A-2",
    persistent = true,
    default = true,
})

hl.workspace_rule({
    workspace = "3",
    monitor = "DP-8",
    persistent = true,
    default = true,
})

hl.config({
    general = {
        border_size = 1,
        -- Keep raw tiled boxes contiguous so Hyprland owns every pointer pixel
        -- in the visible 5 px gap. The asymmetric native insets total 5 px.
        gaps_in = { top = 2, right = 3, bottom = 3, left = 2 },
        gaps_out = 5,
        allow_tearing = false,
        resize_on_border = true,
        extend_border_grab_area = 15,
        hover_icon_on_border = true,
        layout = "lua:obsidience",
        col = {
            active_border = "rgba(67e8f966)",
            inactive_border = "rgb(294b54)",
        },
    },
    decoration = {
        rounding = 12,
        rounding_power = 2,
        active_opacity = 1.0,
        inactive_opacity = 1.0,
        blur = { enabled = false },
        shadow = {
            enabled = true,
            range = 3,
            render_power = 3,
            color = "rgba(22d3ee14)",
        },
        -- OLED mode enables and advances this native inner glow with its grid.
        glow = {
            enabled = false,
            range = 5,
            render_power = 3,
        },
    },
    animations = { enabled = false },
    input = {
        kb_layout = "us",
        follow_mouse = 0,
        sensitivity = 0,
    },
    misc = {
        background_color = "rgb(02060c)",
        disable_hyprland_logo = true,
        disable_splash_rendering = true,
        force_default_wallpaper = 0,
        focus_on_activate = true,
        -- Keep Hyprland fail-secure while allowing the one shell host to
        -- reclaim a lock whose previous client died.
        allow_session_lock_restore = true,
    },
    ecosystem = {
        no_donation_nag = true,
    },
    render = {
        direct_scanout = 0,
    },
    xwayland = {
        enabled = true,
        force_zero_scaling = true,
    },
})

-- Module panes are ordinary xdg-toplevels. Match the process-owned immutable
-- identity, then admit them to the same native layout as applications.
hl.window_rule({
    name = "obsidience-module-pane",
    match = {
        initial_class = [[^io\.obsidience\.shell$]],
        initial_title = [[^obsidience-pane:[a-z][a-z0-9-]{0,47}$]],
    },
    tile = true,
})

-- The classic M.M.O.7 is physically verified at its 6400-DPI top stage.
-- This linear custom curve maps every motion delta to exactly one eighth.
hl.device({
    name = "saitek-cyborg-m.m.o.7-gaming-mouse",
    accel_profile = "custom 1 0 0.125",
    sensitivity = 0,
})

hl.on("hyprland.start", function()
    hl.exec_cmd("systemctl --user start --no-block obsidience-shell-session.target")
end)

hl.bind("SUPER + RETURN", hl.dsp.exec_cmd("uwsm app -- kitty"))
hl.bind("SUPER + Q", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py focused close"))
hl.bind("ALT + TAB", hl.dsp.window.cycle_next())
hl.bind("ALT + SHIFT + TAB", hl.dsp.window.cycle_next({ next = false }))
hl.bind("SUPER + ESCAPE", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py focused close"))
hl.bind("SUPER + SHIFT + ESCAPE", hl.dsp.exit())
hl.bind("SUPER + LEFT", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py focused resize left"))
hl.bind("SUPER + RIGHT", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py focused resize right"))
hl.bind("SUPER + UP", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py focused resize top"))
hl.bind("SUPER + DOWN", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py focused resize bottom"))
hl.bind("SUPER + CTRL + LEFT", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py focused tile left"))
hl.bind("SUPER + CTRL + RIGHT", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py focused tile right"))
hl.bind("SUPER + CTRL + UP", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py focused tile top"))
hl.bind("SUPER + CTRL + DOWN", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py focused tile bottom"))
hl.bind("SUPER + SHIFT + LEFT", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py focused surface left"))
hl.bind("SUPER + SHIFT + RIGHT", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py focused surface right"))
hl.bind("SUPER + SHIFT + UP", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py focused surface top"))
hl.bind("SUPER + SHIFT + DOWN", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py focused surface bottom"))
