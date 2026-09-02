-- Obsidience's minimal Samsung-only Hyprland session.
-- Quickshell owns the visible shell; Hyprland owns composition and windows.

hl.monitor({
    output = "HDMI-A-1",
    mode = "5120x1440@240",
    position = "0x0",
    scale = 1,
    bitdepth = 10,
    vrr = 2,
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
    hl.exec_cmd("systemctl --user start --no-block obsidience-hyprland-session.target")
end)

hl.bind("SUPER + RETURN", hl.dsp.exec_cmd("uwsm app -- kitty"))
hl.bind("SUPER + Q", hl.dsp.window.close())
hl.bind("SUPER + SHIFT + ESCAPE", hl.dsp.exit())
hl.bind("SUPER + SHIFT + LEFT", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience-hyprland/obsidience/shell/input/move_pane.py samsung left"))
hl.bind("SUPER + SHIFT + RIGHT", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience-hyprland/obsidience/shell/input/move_pane.py samsung right"))
hl.bind("SUPER + SHIFT + UP", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience-hyprland/obsidience/shell/input/move_pane.py samsung top"))
hl.bind("SUPER + SHIFT + DOWN", hl.dsp.exec_cmd("/usr/bin/python /home/wissenschafter/Projects/obsidience-hyprland/obsidience/shell/input/move_pane.py samsung bottom"))
