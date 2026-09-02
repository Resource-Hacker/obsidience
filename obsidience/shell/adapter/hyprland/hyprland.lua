-- Obsidience's single-compositor Hyprland session.
-- Quickshell owns the visible shell; Hyprland owns composition and windows.

hl.monitor({
    output = "HDMI-A-1",
    mode = "5120x1440@240",
    position = "0x0",
    scale = 1,
    bitdepth = 10,
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

hl.config({
    general = {
        border_size = 1,
        gaps_in = 0,
        gaps_out = 0,
        allow_tearing = false,
        resize_on_border = true,
    },
    decoration = {
        rounding = 0,
        active_opacity = 1.0,
        inactive_opacity = 1.0,
        blur = { enabled = false },
        shadow = { enabled = false },
    },
    animations = { enabled = false },
    input = {
        kb_layout = "us",
        follow_mouse = 1,
        sensitivity = 0,
    },
    misc = {
        background_color = "rgb(02060c)",
        disable_hyprland_logo = true,
        disable_splash_rendering = true,
        force_default_wallpaper = 0,
        focus_on_activate = true,
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

hl.on("hyprland.start", function()
    hl.exec_cmd("systemctl --user start --no-block obsidience-shell-session.target")
end)

hl.bind("SUPER + RETURN", hl.dsp.exec_cmd("uwsm app -- kitty"))
hl.bind("SUPER + Q", hl.dsp.window.close())
hl.bind("SUPER + SHIFT + ESCAPE", hl.dsp.exit())
hl.bind("SUPER + SHIFT + LEFT", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py focused left"))
hl.bind("SUPER + SHIFT + RIGHT", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py focused right"))
hl.bind("SUPER + SHIFT + UP", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py focused top"))
hl.bind("SUPER + SHIFT + DOWN", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py focused bottom"))
