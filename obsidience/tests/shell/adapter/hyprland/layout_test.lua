local registered_name = nil
local provider = nil
local timers = {}
local config_updates = {}

local WORK_AREAS = {
    ["HDMI-A-1"] = { x = 5, y = 5, w = 5110, h = 1430 },
    ["DP-8"] = { x = 1925, y = 1445, w = 1910, h = 1190 },
    ["HDMI-A-2"] = { x = 5, y = 1445, w = 1910, h = 540 },
}

local function approximately(left, right)
    return math.abs(left - right) < 0.000001
end

local function visual_box(target, box)
    local area = WORK_AREAS[target.window.monitor.name]
    assert(area)
    local left = box.x == area.x and 0 or 2
    local top = box.y == area.y and 0 or 2
    local right = box.x + box.w == area.x + area.w and 0 or 3
    local bottom = box.y + box.h == area.y + area.h and 0 or 3
    return {
        x = box.x + left,
        y = box.y + top,
        w = box.w - left - right,
        h = box.h - top - bottom,
    }
end

local function place_target(target, box)
    target.raw_placed = box
    target.box = box
    target.placed = visual_box(target, box)
    target.placements = (target.placements or 0) + 1
    if target.placement_history then
        table.insert(target.placement_history, target.placed)
    end
end

hl = {
    config = function(value)
        table.insert(config_updates, value)
    end,
    timer = function(callback, options)
        local timer = {
            callback = callback,
            timeout = options.timeout,
            timer_type = options.type,
            enabled = true,
        }
        function timer:set_enabled(enabled)
            self.enabled = enabled
        end
        function timer:set_timeout(timeout)
            self.timeout = timeout
            self.enabled = true
        end
        function timer:is_enabled()
            return self.enabled
        end
        table.insert(timers, timer)
        return timer
    end,
    layout = {
        register = function(name, value)
            registered_name = name
            provider = value
        end,
    },
}

dofile(arg[1])
assert(registered_name == "obsidience")
assert(provider)

local window = {
    stable_id = "stable-7",
    address = "0x7",
    active = true,
    monitor = { name = "HDMI-A-1", dpms_status = true },
    workspace = { id = 1, active = true },
}
local target = {
    index = 1,
    window = window,
    box = { x = 5, y = 5, w = 634, h = 713 },
}
function target:place(box)
    place_target(self, box)
end

local context = {
    area = WORK_AREAS["HDMI-A-1"],
    targets = { target },
}

provider.recalculate(context)
assert(target.placed.x == 5 and target.placed.y == 5)
assert(target.placed.w == 634 and target.placed.h == 713)
local first_placement = target.placed
provider.recalculate(context)
assert(target.placed == first_placement)

-- Restore is the one startup-only path: it applies remembered semantic bounds
-- to the exact mapped address without requiring focus.
window.active = false
assert(provider.layout_msg(
    context, "restore 0x7 samsung 8 2 7 1 8 2") == true)
assert(target.placed.x > 4000 and target.placed.y > 700)
assert(provider.layout_msg(
    context, "restore 0x7 samsung 8 2 0 0 1 1") == true)
assert(target.placed.x == 5 and target.placed.y == 5)
assert(provider.layout_msg(
    context, "restore 0x7 samsung 8 2 7 1 9 2")
    == "obsidience: invalid restore")
window.active = true

assert(provider.layout_msg(context, "resize stable-7 right samsung 8 2")
    == "obsidience: target unavailable")
assert(provider.layout_msg(context, "resize 0X7 right samsung 8 2") == true)
provider.recalculate(context)
assert(target.placed.x == 5 and target.placed.w == 1274)

assert(provider.layout_msg(context, "translate 0x7 right samsung 8 2") == true)
provider.recalculate(context)
assert(target.placed.x == 644 and target.placed.w == 1274)

assert(provider.layout_msg(context, "transfer 0x7 usb-c 3 2 top 0.5") == true)
window.monitor = { name = "DP-8" }
window.workspace = { id = 3 }
context.area = WORK_AREAS["DP-8"]
provider.recalculate(context)
assert(target.placed.x == 2563 and target.placed.y == 1445)
assert(target.placed.w == 1272 and target.placed.h == 593)

window.active = false
assert(provider.layout_msg(
    context, "place 0x7 usb-c 3 2 0 0 1 1") == true)
assert(target.placed.x == 1925 and target.placed.y == 1445)
local placement_count = target.placements
assert(provider.layout_msg(
    context, "verify-place 0x7 usb-c 3 2 0 0 1 1") == true)
assert(target.placements == placement_count)
assert(provider.layout_msg(
    context, "verify-place 0x7 usb-c 3 2 1 0 2 1")
    == "obsidience: placement not observed")
assert(provider.layout_msg(
    context, "verify-place 0x7 samsung 8 2 0 0 1 1")
    == "obsidience: placement not observed")
assert(provider.layout_msg(
    context, "verify-place 0x7 usb-c 4 2 0 0 1 1")
    == "obsidience: placement not observed")
assert(provider.layout_msg(
    context, "verify-place 0x99 usb-c 3 2 0 0 1 1")
    == "obsidience: target unavailable")
window.stable_id = "replacement-7"
assert(provider.layout_msg(
    context, "verify-place 0x7 usb-c 3 2 0 0 1 1")
    == "obsidience: placement not observed")
window.stable_id = "stable-7"
assert(provider.layout_msg(
    context, "verify-place 0x7 usb-c 3 2 0 0 1920 1440")
    == "obsidience: invalid placement verification")
local settled_box = target.box
target.box = { x = 2200, y = 1445, w = 632, h = 593 }
assert(provider.layout_msg(
    context, "verify-place 0x7 usb-c 3 2 0 0 1 1")
    == "obsidience: placement not observed")
target.box = settled_box
assert(target.placements == placement_count)
assert(provider.layout_msg(context, "place 0x7 dp-4 4 1") == true)
assert(provider.layout_msg(
    context, "verify-place 0x7 usb-c 3 2 0 0 1 1")
    == "obsidience: placement not observed")
window.monitor = { name = "HDMI-A-2" }
window.workspace = { id = 11 }
context.area = WORK_AREAS["HDMI-A-2"]
provider.recalculate(context)
assert(target.placed.x > 5 and target.placed.y == 1445)
assert(provider.layout_msg(context, "place-cancel 0x7") == true)
assert(provider.layout_msg(context, "resize 0x7 left usb-c 3 2")
    == "obsidience: target is not active")
assert(provider.layout_msg(context, "cancel 0x7")
    == "obsidience: target is not active")
assert(provider.layout_msg(context, "resize 0x99 left usb-c 3 2")
    == "obsidience: target unavailable")

local second_window = {
    stable_id = "stable-8",
    address = "0x8",
    active = false,
    monitor = { name = "HDMI-A-2" },
    workspace = { id = 10 },
}
local third_window = {
    stable_id = "stable-9",
    address = "0x9",
    active = true,
    monitor = { name = "HDMI-A-2" },
    workspace = { id = 10 },
}
local second_target = {
    index = 1,
    window = second_window,
    box = { x = 0, y = 1440, w = 480, h = 550 },
}
local third_target = {
    index = 2,
    window = third_window,
    box = { x = 0, y = 1440, w = 480, h = 550 },
}
function second_target:place(box)
    place_target(self, box)
end
function third_target:place(box)
    place_target(self, box)
end

provider.recalculate({
    area = WORK_AREAS["HDMI-A-2"],
    targets = { second_target, third_target },
})
assert(second_target.placed.x == 5)
assert(third_target.placed.x == 5)
assert(second_target.placed.w == third_target.placed.w)
assert(second_target.placed.h == third_target.placed.h)

local overlap_context = {
    area = WORK_AREAS["HDMI-A-2"],
    targets = { second_target, third_target },
}
assert(provider.layout_msg(overlap_context, "translate 0x9 right dp-4 4 1") == true)
provider.recalculate(overlap_context)
assert(second_target.placed.x == 5)
assert(third_target.placed.x == 484)

-- Tile bounds are placement coordinates, not occupancy locks. A native drag
-- may place one tracked client over another without changing focus itself.
second_window.active = true
third_window.active = false
second_target.box = {
    x = third_target.placed.x,
    y = third_target.placed.y,
    w = third_target.placed.w,
    h = third_target.placed.h,
}
provider.recalculate(overlap_context)
assert(second_target.box.x == third_target.box.x)
assert(second_target.box.y == third_target.box.y)
assert(second_target.box.w == third_target.box.w)
assert(second_target.box.h == third_target.box.h)
assert(second_window.active == true)
assert(third_window.active == false)

-- A genuinely new client still receives the first free default tile.
local fourth_window = {
    stable_id = "stable-b",
    address = "0xb",
    active = false,
    monitor = { name = "HDMI-A-2" },
    workspace = { id = 10 },
}
local fourth_target = {
    index = 3,
    window = fourth_window,
    box = { x = 0, y = 1440, w = 480, h = 550 },
}
function fourth_target:place(box)
    place_target(self, box)
end
overlap_context.targets = { second_target, third_target, fourth_target }
provider.recalculate(overlap_context)
assert(fourth_target.placed.x == 5)

local drop_window = {
    stable_id = "stable-a",
    address = "0xa",
    active = true,
    monitor = { name = "HDMI-A-1", dpms_status = true },
    workspace = { id = 11 },
}
local drop_target = {
    index = 1,
    window = drop_window,
    box = { x = 5, y = 5, w = 634, h = 713 },
}
function drop_target:place(box)
    place_target(self, box)
end
local drop_context = {
    area = WORK_AREAS["HDMI-A-1"],
    targets = { drop_target },
}
provider.recalculate(drop_context)
drop_target.box = { x = 1284, y = 723, w = 634, h = 712 }
provider.recalculate(drop_context)
assert(drop_target.placed.x == 1284 and drop_target.placed.y == 723)
assert(drop_target.placed.w == 634 and drop_target.placed.h == 712)

-- A Settings grid update is independent of focus and applies to the very next
-- client-native pointer drop, before any keyboard layout command is needed.
drop_window.active = false
assert(provider.layout_msg(drop_context, "grid samsung 4 2") == true)
assert(provider.layout_msg(drop_context, "grid samsung 0 2")
    == "obsidience: invalid grid")
provider.recalculate(drop_context)
drop_target.box = { x = 2563, y = 723, w = 1273, h = 712 }
provider.recalculate(drop_context)
assert(drop_target.placed.x == 2563 and drop_target.placed.y == 723)
assert(drop_target.placed.w == 1273 and drop_target.placed.h == 712)

-- Native pointer resizing moves shared grid cuts. Each adjacent base cell stays
-- within the configured percentage even when both of its cuts have moved.
assert(provider.layout_msg(drop_context, "grid samsung 8 2") == true)
local resize_workspace = { id = 20, active = true, has_fullscreen = false }
local resize_window = {
    stable_id = "resize-left",
    address = "0x20",
    active = true,
    monitor = { name = "HDMI-A-1", dpms_status = true },
    workspace = resize_workspace,
}
local resize_right_window = {
    stable_id = "resize-right",
    address = "0x21",
    active = false,
    monitor = { name = "HDMI-A-1", dpms_status = true },
    workspace = resize_workspace,
}
local resize_bottom_window = {
    stable_id = "resize-bottom",
    address = "0x22",
    active = false,
    monitor = { name = "HDMI-A-1", dpms_status = true },
    workspace = resize_workspace,
}
local resize_full_window = {
    stable_id = "resize-full",
    address = "0x23",
    active = false,
    monitor = { name = "HDMI-A-1", dpms_status = true },
    workspace = resize_workspace,
}
local resize_target = {
    index = 1,
    window = resize_window,
    box = { x = 5, y = 5, w = 634, h = 713 },
    placements = 0,
}
local resize_right_target = {
    index = 2,
    window = resize_right_window,
    box = { x = 644, y = 5, w = 635, h = 713 },
    placements = 0,
}
local resize_bottom_target = {
    index = 3,
    window = resize_bottom_window,
    box = { x = 5, y = 723, w = 634, h = 712 },
    placements = 0,
}
local resize_full_target = {
    index = 4,
    window = resize_full_window,
    box = { x = 5, y = 5, w = 5110, h = 1430 },
    placements = 0,
}
for _, resize_test_target in ipairs({
    resize_target,
    resize_right_target,
    resize_bottom_target,
    resize_full_target,
}) do
    function resize_test_target:place(box)
        place_target(self, box)
    end
end
local resize_context = {
    area = WORK_AREAS["HDMI-A-1"],
    targets = {
        resize_target,
        resize_right_target,
        resize_bottom_target,
        resize_full_target,
    },
}
provider.recalculate(resize_context)
assert(resize_target.placements == 1)
assert(resize_full_target.placements == 1)
assert(resize_target.raw_placed.x + resize_target.raw_placed.w
    == resize_right_target.raw_placed.x)
assert(resize_target.placed.x + resize_target.placed.w + 5
    == resize_right_target.placed.x)
provider.recalculate(resize_context)
assert(resize_target.placements == 1)
assert(resize_full_target.placements == 1)

provider.resize(resize_context, resize_target, 1000, 1000, "bottom-right")
provider.recalculate(resize_context)
assert(resize_target.placed.w == 792 and resize_target.placed.h == 891)
assert(resize_right_target.placed.x == 802)
assert(resize_target.placed.x + resize_target.placed.w + 5 == resize_right_target.placed.x)
assert(resize_bottom_target.placed.y == 901)
assert(resize_target.placed.y + resize_target.placed.h + 5 == resize_bottom_target.placed.y)
assert(resize_right_target.placed.y == 5 and resize_right_target.placed.h == 713)
assert(resize_full_target.placed.x == 5 and resize_full_target.placed.w == 5110)
assert(resize_full_target.placed.y == 5 and resize_full_target.placed.h == 1430)

-- The next cut cannot combine with the first cut to shrink the middle cell by
-- twice the configured 25 percent.
provider.resize(resize_context, resize_right_target, -1000, 0, "right")
provider.recalculate(resize_context)
assert(resize_right_target.placed.w == 477)

provider.resize(resize_context, resize_target, -1000, -1000, "bottom-right")
provider.recalculate(resize_context)
assert(resize_target.placed.w == 476 and resize_target.placed.h == 535)
assert(resize_target.placed.x + resize_target.placed.w + 5 == resize_right_target.placed.x)
assert(resize_target.placed.y + resize_target.placed.h + 5 == resize_bottom_target.placed.y)

-- Settings is target-free and validates the exact UI transport ranges.
resize_window.active = false
assert(provider.layout_msg(resize_context, "settings 26 0 50 3600 1 0")
    == "obsidience: invalid settings")
assert(provider.layout_msg(resize_context, "settings -1 0 50 3600 1")
    == "obsidience: invalid settings")
assert(provider.layout_msg(resize_context, "settings 25 2 50 3600 1 0")
    == "obsidience: invalid settings")
assert(provider.layout_msg(resize_context, "settings 25 0 0 3600 1 0")
    == "obsidience: invalid settings")
assert(provider.layout_msg(resize_context, "settings 25 0 51 3600 1 0")
    == "obsidience: invalid settings")
assert(provider.layout_msg(resize_context, "settings 25 0 50 59 1 0")
    == "obsidience: invalid settings")
assert(provider.layout_msg(resize_context, "settings 25 0 50 86401 1 0")
    == "obsidience: invalid settings")
assert(provider.layout_msg(resize_context, "settings 25 0 50 3600 0 0")
    == "obsidience: invalid settings")
assert(provider.layout_msg(resize_context, "settings 25 0 50 3600 25 0")
    == "obsidience: invalid settings")
assert(provider.layout_msg(resize_context, "settings 25 0 32 3600 3 0") == true)
assert(provider.layout_msg(resize_context, "settings 0 0 50 3600 1 0") == true)
assert(resize_target.placed.w == 634 and resize_target.placed.h == 713)
local disabled_width = resize_target.placed.w
provider.resize(resize_context, resize_target, 100, 100, "bottom-right")
provider.recalculate(resize_context)
assert(resize_target.placed.w == disabled_width)

-- OLED movement uses one shared one-second Hyprland timer. Independently phased seams
-- share one coordinate between their neighbors, while outer edges stay fixed.
local usb_workspace = { id = 21, active = true, has_fullscreen = false }
local usb_window = {
    stable_id = "oled-usb",
    address = "0x24",
    active = false,
    monitor = { name = "DP-8" },
    workspace = usb_workspace,
}
local usb_target = {
    index = 1,
    window = usb_window,
    box = { x = 5, y = 5, w = 633, h = 593 },
    placements = 0,
}
function usb_target:place(box)
    place_target(self, box)
end
local usb_context = {
    area = WORK_AREAS["DP-8"],
    targets = { usb_target },
}
provider.recalculate(usb_context)
local usb_placements = usb_target.placements
local pre_oled_placements = resize_target.placements
local pre_oled_full_placements = resize_full_target.placements
local pre_oled_box = resize_target.placed
local pre_oled_right_box = resize_right_target.placed
local pre_oled_bottom_box = resize_bottom_target.placed
assert(provider.layout_msg(resize_context, "settings 25 1 32 3600 3 0") == true)
assert(#timers == 1)
assert(timers[1].timer_type == "repeat")
assert(timers[1].timeout == 1000)
assert(timers[1].enabled == true)
assert(resize_target.placed == pre_oled_box)
assert(resize_right_target.placed == pre_oled_right_box)
assert(resize_bottom_target.placed == pre_oled_bottom_box)
assert(resize_target.placements == pre_oled_placements)
assert(resize_full_target.placements == pre_oled_full_placements)
assert(config_updates[#config_updates].decoration.glow.color.angle == 0)

-- Secure lock freezes both the geometry and glow clock with no catch-up.
assert(provider.layout_msg(
    resize_context, "settings 25 1 32 3600 3 1") == true)
local locked_box = resize_target.placed
local locked_placements = resize_target.placements
local locked_config_updates = #config_updates
for _ = 1, 10 do
    timers[1].callback()
end
assert(resize_target.placed == locked_box)
assert(resize_target.placements == locked_placements)
assert(#config_updates == locked_config_updates)
assert(provider.layout_msg(
    resize_context, "settings 25 1 32 3600 3 0") == true)

local function run_oled_ticks(count)
    for _ = 1, count do
        timers[1].callback()
    end
end

local first_tick_updates = #config_updates
run_oled_ticks(59)
assert(#config_updates == first_tick_updates)
run_oled_ticks(1)
assert(#config_updates == first_tick_updates + 1)
assert(config_updates[#config_updates].decoration.glow.color.angle == 2)
assert(resize_target.placed.x + resize_target.placed.w + 5 == resize_right_target.placed.x)
assert(resize_target.placed.y + resize_target.placed.h + 5 == resize_bottom_target.placed.y)
assert(resize_full_target.placed.x == 5 and resize_full_target.placed.w == 5110)
assert(resize_full_target.placements == pre_oled_full_placements)
assert(usb_target.placements == usb_placements)

-- Fullscreen freezes placement and the native glow phase, protecting 240 Hz.
resize_workspace.has_fullscreen = true
local fullscreen_box = resize_target.placed
local fullscreen_placements = resize_target.placements
local fullscreen_config_updates = #config_updates
timers[1].callback()
assert(resize_target.placed == fullscreen_box)
assert(resize_target.placements == fullscreen_placements)
assert(#config_updates == fullscreen_config_updates)
resize_workspace.has_fullscreen = false
run_oled_ticks(59)
assert(#config_updates == fullscreen_config_updates)
run_oled_ticks(1)
assert(config_updates[#config_updates].decoration.glow.color.angle == 4)
assert(usb_target.placements == usb_placements)

-- A DPMS-off Samsung is not a visible OLED context. Its physical and glow
-- clocks pause without a configuration or placement write, then resume from
-- the same active-time phase instead of catching up.
resize_window.monitor.dpms_status = false
local dpms_box = resize_target.placed
local dpms_placements = resize_target.placements
local dpms_config_updates = #config_updates
timers[1].callback()
assert(resize_target.placed == dpms_box)
assert(resize_target.placements == dpms_placements)
assert(#config_updates == dpms_config_updates)
resize_window.monitor.dpms_status = true
run_oled_ticks(59)
assert(#config_updates == dpms_config_updates)
run_oled_ticks(1)
assert(config_updates[#config_updates].decoration.glow.color.angle == 6)

resize_workspace.active = false
local hidden_box = resize_target.placed
local hidden_placements = resize_target.placements
local hidden_config_updates = #config_updates
timers[1].callback()
assert(resize_target.placed == hidden_box)
assert(resize_target.placements == hidden_placements)
assert(#config_updates == hidden_config_updates)
resize_workspace.active = true
run_oled_ticks(59)
assert(#config_updates == hidden_config_updates)
run_oled_ticks(1)
assert(config_updates[#config_updates].decoration.glow.color.angle == 8)

-- Disabling restores the semantic grid once and leaves the timer dormant.
assert(provider.layout_msg(resize_context, "settings 25 0 32 3600 3 0") == true)
assert(timers[1].enabled == false)
assert(resize_target.placed.x == 5 and resize_target.placed.w == 634)
assert(resize_right_target.placed.x == 644 and resize_right_target.placed.w == 635)
assert(resize_target.placed.x + resize_target.placed.w + 5 == resize_right_target.placed.x)
local restored_box = resize_target.placed
local restored_placements = resize_target.placements
timers[1].callback()
assert(resize_target.placed == restored_box)
assert(resize_target.placements == restored_placements)

-- Two top/bottom pairs can move their horizontal separators independently.
local segmented_workspace = { id = 23, active = true, has_fullscreen = false }
local function segmented_target(id, address, index, box, active)
    local value = {
        index = index,
        window = {
            stable_id = id,
            address = address,
            active = active,
            monitor = { name = "HDMI-A-1", dpms_status = true },
            workspace = segmented_workspace,
        },
        box = box,
        placements = 0,
    }
    function value:place(placed)
        place_target(self, placed)
    end
    return value
end
local segmented_top_left = segmented_target(
    "segmented-top-left", "0x60", 1,
    { x = 5, y = 5, w = 634, h = 713 }, true)
local segmented_bottom_left = segmented_target(
    "segmented-bottom-left", "0x61", 2,
    { x = 5, y = 723, w = 634, h = 712 }, false)
local segmented_top_right = segmented_target(
    "segmented-top-right", "0x62", 3,
    { x = 644, y = 5, w = 635, h = 713 }, false)
local segmented_bottom_right = segmented_target(
    "segmented-bottom-right", "0x63", 4,
    { x = 644, y = 723, w = 635, h = 712 }, false)
local segmented_context = {
    area = WORK_AREAS["HDMI-A-1"],
    targets = {
        segmented_top_left,
        segmented_bottom_left,
        segmented_top_right,
        segmented_bottom_right,
    },
}
provider.recalculate(segmented_context)
provider.resize(segmented_context, segmented_top_left, 0, 1000, "bottom")
provider.recalculate(segmented_context)
assert(segmented_top_left.placed.h == 891)
assert(segmented_bottom_left.placed.y == 901)
assert(segmented_top_right.placed.y == 5 and segmented_top_right.placed.h == 713)
assert(segmented_bottom_right.placed.y == 723 and segmented_bottom_right.placed.h == 712)
assert(segmented_top_left.placed.y + segmented_top_left.placed.h + 5
    == segmented_bottom_left.placed.y)
assert(segmented_top_right.placed.y + segmented_top_right.placed.h + 5
    == segmented_bottom_right.placed.y)

-- Disconnected horizontal components receive independent deterministic
-- phases, but every pane sharing one segment receives the exact same cut.
local segmented_left_baseline = segmented_top_left.placed.h
local segmented_right_baseline = segmented_top_right.placed.h
assert(provider.layout_msg(
    segmented_context, "settings 25 1 32 60 3 0") == true)
assert(segmented_top_left.placed.h == segmented_left_baseline)
assert(segmented_top_right.placed.h == segmented_right_baseline)
local maximum_y_component_divergence = 0
for _ = 1, 60 do
    timers[1].callback()
    local left_offset = segmented_top_left.placed.h - segmented_left_baseline
    local right_offset = segmented_top_right.placed.h - segmented_right_baseline
    maximum_y_component_divergence = math.max(
        maximum_y_component_divergence,
        math.abs(left_offset - right_offset))
    assert(segmented_top_left.placed.y + segmented_top_left.placed.h + 5
        == segmented_bottom_left.placed.y)
    assert(segmented_top_right.placed.y + segmented_top_right.placed.h + 5
        == segmented_bottom_right.placed.y)
end
assert(maximum_y_component_divergence >= 20)
assert(provider.layout_msg(
    segmented_context, "settings 25 0 32 60 3 0") == true)
segmented_workspace.active = false

-- Horizontal cuts are independent by column until a pane spans them. The
-- spanning pane deliberately joins only the segments beneath its straight edge.
local coupled_workspace = { id = 24, active = true, has_fullscreen = false }
local function coupled_target(id, address, index, box, active)
    local value = {
        index = index,
        window = {
            stable_id = id,
            address = address,
            active = active,
            monitor = { name = "HDMI-A-1", dpms_status = true },
            workspace = coupled_workspace,
        },
        box = box,
        placements = 0,
    }
    function value:place(placed)
        place_target(self, placed)
    end
    return value
end
local coupled_top = coupled_target(
    "coupled-top", "0x50", 1, { x = 5, y = 5, w = 1274, h = 713 }, true)
local coupled_bottom_left = coupled_target(
    "coupled-bottom-left", "0x51", 2,
    { x = 5, y = 723, w = 634, h = 712 }, false)
local coupled_bottom_right = coupled_target(
    "coupled-bottom-right", "0x52", 3,
    { x = 644, y = 723, w = 635, h = 712 }, false)
local coupled_context = {
    area = WORK_AREAS["HDMI-A-1"],
    targets = { coupled_top, coupled_bottom_left, coupled_bottom_right },
}
provider.recalculate(coupled_context)
provider.resize(coupled_context, coupled_top, 0, 1000, "bottom")
provider.recalculate(coupled_context)
assert(coupled_top.placed.h == 891)
assert(coupled_bottom_left.placed.y == 901)
assert(coupled_bottom_right.placed.y == 901)
assert(coupled_top.placed.y + coupled_top.placed.h + 5
    == coupled_bottom_left.placed.y)
assert(coupled_top.placed.y + coupled_top.placed.h + 5
    == coupled_bottom_right.placed.y)
coupled_workspace.active = false

-- PaneFrame currently exposes only a bottom-right handle. Edge tiles therefore
-- resize through their opposite interior cut while the Surface edge stays put.
local edge_workspace = { id = 22, active = true, has_fullscreen = false }
local function edge_target(id, index, box)
    local value = {
        index = index,
        window = {
            stable_id = id,
            address = "0x" .. tostring(30 + index),
            active = false,
            monitor = { name = "HDMI-A-1", dpms_status = true },
            workspace = edge_workspace,
        },
        box = box,
        placements = 0,
    }
    function value:place(placed)
        place_target(self, placed)
    end
    return value
end

local last_column_target = edge_target(
    "edge-last-column", 1, { x = 4481, y = 5, w = 634, h = 713 })
local bottom_row_target = edge_target(
    "edge-bottom-row", 2, { x = 5, y = 723, w = 634, h = 712 })
local bottom_right_target = edge_target(
    "edge-bottom-right", 3, { x = 4481, y = 723, w = 634, h = 712 })
local top_left_target = edge_target(
    "edge-top-left", 4, { x = 5, y = 5, w = 634, h = 713 })
local full_span_target = edge_target(
    "edge-full-span", 5, { x = 5, y = 5, w = 5110, h = 1430 })
local edge_context = {
    area = WORK_AREAS["HDMI-A-1"],
    targets = {
        last_column_target,
        bottom_row_target,
        bottom_right_target,
        top_left_target,
        full_span_target,
    },
}
provider.recalculate(edge_context)

provider.resize(edge_context, last_column_target, 1000, 0, "bottom-right")
provider.recalculate(edge_context)
assert(last_column_target.placed.x == 4323 and last_column_target.placed.w == 792)
assert(last_column_target.placed.x + last_column_target.placed.w == 5115)

assert(provider.layout_msg(edge_context, "settings 0 0 50 3600 1 0") == true)
assert(provider.layout_msg(edge_context, "settings 25 0 50 3600 1 0") == true)
provider.resize(edge_context, bottom_row_target, 0, 1000, "bottom-right")
provider.recalculate(edge_context)
assert(bottom_row_target.placed.y == 545 and bottom_row_target.placed.h == 890)
assert(bottom_row_target.placed.y + bottom_row_target.placed.h == 1435)

assert(provider.layout_msg(edge_context, "settings 0 0 50 3600 1 0") == true)
assert(provider.layout_msg(edge_context, "settings 25 0 50 3600 1 0") == true)
provider.resize(edge_context, bottom_right_target, 1000, 1000, "bottom-right")
provider.recalculate(edge_context)
assert(bottom_right_target.placed.x == 4323 and bottom_right_target.placed.w == 792)
assert(bottom_right_target.placed.y == 545 and bottom_right_target.placed.h == 890)
assert(bottom_right_target.placed.x + bottom_right_target.placed.w == 5115)
assert(bottom_right_target.placed.y + bottom_right_target.placed.h == 1435)

-- Symmetric fallbacks keep future left/top handles useful at their fixed edges.
assert(provider.layout_msg(edge_context, "settings 0 0 50 3600 1 0") == true)
assert(provider.layout_msg(edge_context, "settings 25 0 50 3600 1 0") == true)
provider.resize(edge_context, top_left_target, -1000, -1000, "top-left")
provider.recalculate(edge_context)
assert(top_left_target.placed.x == 5 and top_left_target.placed.w == 792)
assert(top_left_target.placed.y == 5 and top_left_target.placed.h == 891)

-- Both boundaries are fixed on a full-span axis, so no fallback cut exists.
assert(provider.layout_msg(edge_context, "settings 0 0 50 3600 1 0") == true)
assert(provider.layout_msg(edge_context, "settings 25 0 50 3600 1 0") == true)
local full_span_box = full_span_target.placed
local full_span_placements = full_span_target.placements
provider.resize(edge_context, full_span_target, 1000, 1000, "bottom-right")
provider.recalculate(edge_context)
assert(full_span_target.placed == full_span_box)
assert(full_span_target.placements == full_span_placements)
assert(full_span_target.placed.x == 5 and full_span_target.placed.w == 5110)
assert(full_span_target.placed.y == 5 and full_span_target.placed.h == 1430)

-- Hyprland omits the empty callback when the final target leaves a workspace.
-- A retained source callback must never place that live target with its old
-- Surface area during a later OLED/settings refresh.
resize_workspace.active = false
usb_workspace.active = false
edge_workspace.active = false
local migrated_source_workspace = { id = 30, active = true, has_fullscreen = false }
local migrated_window = {
    stable_id = "migrated",
    address = "0x40",
    active = true,
    monitor = { name = "DP-8" },
    workspace = migrated_source_workspace,
}
local migrated_target = {
    index = 1,
    window = migrated_window,
    box = { x = 1925, y = 1445, w = 633, h = 593 },
    placements = 0,
    placement_history = {},
}
function migrated_target:place(box)
    place_target(self, box)
end
local migrated_source_context = {
    area = WORK_AREAS["DP-8"],
    targets = { migrated_target },
}
provider.recalculate(migrated_source_context)
assert(provider.layout_msg(
    migrated_source_context, "transfer 0x40 samsung 8 2 bottom 0.125") == true)

local migrated_destination_workspace = {
    id = 31,
    active = true,
    has_fullscreen = false,
}
migrated_window.monitor = { name = "HDMI-A-1", dpms_status = true }
migrated_window.workspace = migrated_destination_workspace
local migrated_destination_context = {
    area = WORK_AREAS["HDMI-A-1"],
    targets = { migrated_target },
}
provider.recalculate(migrated_destination_context)
local destination_history_start = #migrated_target.placement_history
assert(provider.layout_msg(
    migrated_destination_context, "settings 25 1 32 60 3 0") == true)
assert(config_updates[#config_updates].decoration.glow.enabled == true)
assert(config_updates[#config_updates].decoration.glow.range == 5)
assert(config_updates[#config_updates].decoration.glow.color.angle == 0)
assert(config_updates[#config_updates].general.col.active_border.angle == 0)
local migrated_config_updates = #config_updates
run_oled_ticks(59)
assert(#config_updates == migrated_config_updates)
run_oled_ticks(1)
assert(approximately(
    config_updates[#config_updates].decoration.glow.color.angle, 2))
assert(approximately(
    config_updates[#config_updates].general.col.active_border.angle, 2))
assert(#migrated_target.placement_history >= destination_history_start)
for index = destination_history_start, #migrated_target.placement_history do
    local placed = migrated_target.placement_history[index]
    assert(placed.x >= 5 and placed.y >= 5)
    assert(placed.x + placed.w <= 5115)
    assert(placed.y + placed.h <= 1435)
end

-- Manual resizing owns the configured percentage limit. OLED displacement is
-- a separate shared offset and may move the resulting cut beyond that manual
-- allowance while still retaining positive cells and exact native gaps.
assert(provider.layout_msg(
    migrated_destination_context, "settings 25 0 32 60 3 0") == true)
migrated_destination_workspace.active = false
local independent_workspace = { id = 32, active = true, has_fullscreen = false }
local independent_left = edge_target(
    "independent-left", 20, { x = 5, y = 5, w = 634, h = 713 })
local independent_right = edge_target(
    "independent-right", 21, { x = 644, y = 5, w = 635, h = 713 })
local independent_third = edge_target(
    "independent-third", 22, { x = 1284, y = 5, w = 634, h = 713 })
independent_left.window.workspace = independent_workspace
independent_right.window.workspace = independent_workspace
independent_third.window.workspace = independent_workspace
independent_left.window.active = true
local independent_context = {
    area = WORK_AREAS["HDMI-A-1"],
    targets = { independent_left, independent_right, independent_third },
}
provider.recalculate(independent_context)
provider.resize(independent_context, independent_left, 1000, 0, "right")
provider.recalculate(independent_context)
local regular_width = 634
local manual_width = independent_left.placed.w
assert(manual_width == regular_width + math.floor(regular_width * 0.25))
assert(provider.layout_msg(independent_context, "settings 25 1 32 60 3 0") == true)
assert(independent_left.placed.w == manual_width)
timers[1].callback()
assert(math.abs(independent_left.placed.w - manual_width) <= 32)
assert(independent_left.placed.x + independent_left.placed.w + 5
    == independent_right.placed.x)
assert(independent_right.placed.x + independent_right.placed.w + 5
    == independent_third.placed.x)
assert(independent_left.raw_placed.x + independent_left.raw_placed.w
    == independent_right.raw_placed.x)
assert(independent_left.placed.x >= 5)
assert(independent_third.placed.x + independent_third.placed.w <= 5115)
assert(provider.layout_msg(independent_context, "settings 25 0 32 60 3 0") == true)
assert(config_updates[#config_updates].decoration.glow.enabled == false)
assert(config_updates[#config_updates].general.col.active_border == "rgba(67e8f966)")
assert(config_updates[#config_updates].general.col.inactive_border == "rgb(294b54)")
local first_seam_cap = math.floor(math.min(
    independent_left.raw_placed.w,
    independent_right.raw_placed.w) * 0.05)
local second_seam_cap = math.floor(math.min(
    independent_right.raw_placed.w,
    independent_third.raw_placed.w) * 0.05)

-- A 24-active-minute simulation at the shortest supported travel duration
-- covers six reflected cycles. It checks
-- bounded, constant-speed seam dwell, dephasing, shared gaps, and the one
-- compositor-style write per active minute ceiling.
assert(provider.layout_msg(independent_context, "settings 25 1 32 60 3 0") == true)
local simulation_config_start = #config_updates
local minimum_offset, maximum_offset = math.huge, -math.huge
local offset_sum, sample_count = 0, 0
local offset_dwell = {}
local maximum_seam_divergence = 0
for _ = 1, 24 * 60 do
    timers[1].callback()
    local first_offset = independent_left.placed.w - manual_width
    local second_offset = independent_third.placed.x - 1284
    minimum_offset = math.min(minimum_offset, first_offset)
    maximum_offset = math.max(maximum_offset, first_offset)
    offset_sum = offset_sum + first_offset
    sample_count = sample_count + 1
    offset_dwell[first_offset] = (offset_dwell[first_offset] or 0) + 1
    maximum_seam_divergence = math.max(
        maximum_seam_divergence,
        math.abs(first_offset - second_offset))
    assert(math.abs(first_offset) <= first_seam_cap)
    assert(math.abs(second_offset) <= second_seam_cap)
    assert(independent_left.placed.w > 0)
    assert(independent_right.placed.w > 0)
    assert(independent_third.placed.w > 0)
    assert(independent_left.placed.x + independent_left.placed.w + 5
        == independent_right.placed.x)
    assert(independent_right.placed.x + independent_right.placed.w + 5
        == independent_third.placed.x)
end
local unique_offsets = 0
local minimum_dwell, maximum_dwell = math.huge, 0
for offset, dwell in pairs(offset_dwell) do
    unique_offsets = unique_offsets + 1
    if offset > minimum_offset and offset < maximum_offset then
        minimum_dwell = math.min(minimum_dwell, dwell)
        maximum_dwell = math.max(maximum_dwell, dwell)
    end
end
assert(minimum_offset <= -20 and maximum_offset >= 20)
assert(unique_offsets >= 40)
assert(math.abs(offset_sum / sample_count) < 2)
assert(maximum_dwell <= minimum_dwell * 2)
assert(maximum_seam_divergence >= 20)
assert(#config_updates - simulation_config_start == 24)
assert(approximately(
    config_updates[#config_updates].decoration.glow.color.angle, 48))
assert(#timers == 1)
assert(timers[1].timeout == 1000)
assert(provider.layout_msg(independent_context, "settings 25 0 32 3600 3 0") == true)
independent_workspace.active = false

-- The complete default Samsung row starts exactly centered, then traverses the
-- shortened one-minute test path through one-pixel-or-smaller rounded steps.
local phase_workspace = { id = 33, active = true, has_fullscreen = false }
local phase_targets = {}
for column = 0, 7 do
    local phase_target = {
        index = column + 1,
        window = {
            stable_id = "phase-" .. tostring(column),
            address = string.format("0x%x", 112 + column),
            active = column == 0,
            monitor = { name = "HDMI-A-1", dpms_status = true },
            workspace = phase_workspace,
        },
        box = { x = 5 + column * 639, y = 5, w = 634, h = 713 },
        placements = 0,
    }
    function phase_target:place(box)
        place_target(self, box)
    end
    table.insert(phase_targets, phase_target)
end
local phase_context = {
    area = WORK_AREAS["HDMI-A-1"],
    targets = phase_targets,
}
provider.recalculate(phase_context)
local phase_boundaries = {}
local phase_placements = {}
for index, phase_target in ipairs(phase_targets) do
    phase_placements[index] = phase_target.placements
    if index < #phase_targets then
        phase_boundaries[index] = phase_target.raw_placed.x
            + phase_target.raw_placed.w
        assert(phase_boundaries[index] == phase_targets[index + 1].raw_placed.x)
    end
end
assert(provider.layout_msg(phase_context, "settings 25 1 32 60 3 0") == true)
for index, phase_target in ipairs(phase_targets) do
    assert(phase_target.placements == phase_placements[index])
    if index < #phase_targets then
        assert(phase_target.raw_placed.x + phase_target.raw_placed.w
            == phase_boundaries[index])
    end
end
local minimum_seam_offset = math.huge
local maximum_seam_offset = -math.huge
local distinct_seam_offsets = {}
local previous_boundaries = {}
for index, boundary in ipairs(phase_boundaries) do
    previous_boundaries[index] = boundary
end
local changed_ticks = 0
for tick = 1, 60 do
    timers[1].callback()
    local tick_changed = false
    for index = 1, #phase_targets - 1 do
        local boundary = phase_targets[index].raw_placed.x
            + phase_targets[index].raw_placed.w
        local offset = boundary - phase_boundaries[index]
        minimum_seam_offset = math.min(minimum_seam_offset, offset)
        maximum_seam_offset = math.max(maximum_seam_offset, offset)
        distinct_seam_offsets[offset] = true
        assert(boundary == phase_targets[index + 1].raw_placed.x)
        if previous_boundaries[index] ~= nil then
            local step = math.abs(boundary - previous_boundaries[index])
            assert(step <= 1)
            tick_changed = tick_changed or step > 0
        end
        previous_boundaries[index] = boundary
    end
    if tick_changed then
        changed_ticks = changed_ticks + 1
    end
end
local distinct_seam_count = 0
for _ in pairs(distinct_seam_offsets) do
    distinct_seam_count = distinct_seam_count + 1
end
assert(minimum_seam_offset <= -28)
assert(maximum_seam_offset >= 28)
assert(maximum_seam_offset - minimum_seam_offset >= 56)
assert(distinct_seam_count >= 40)
assert(changed_ticks >= 30)
assert(phase_targets[1].raw_placed.x == 5)
local last_phase_target = phase_targets[#phase_targets]
assert(last_phase_target.raw_placed.x + last_phase_target.raw_placed.w == 5115)
local duration_change_placements = {}
local duration_change_boundaries = {}
for index, phase_target in ipairs(phase_targets) do
    duration_change_placements[index] = phase_target.placements
    if index < #phase_targets then
        duration_change_boundaries[index] = phase_target.raw_placed.x
            + phase_target.raw_placed.w
    end
end
assert(provider.layout_msg(phase_context, "settings 25 1 32 3600 3 0") == true)
for index, phase_target in ipairs(phase_targets) do
    assert(phase_target.placements == duration_change_placements[index])
    if index < #phase_targets then
        assert(phase_target.raw_placed.x + phase_target.raw_placed.w
            == duration_change_boundaries[index])
    end
end
assert(provider.layout_msg(phase_context, "settings 25 0 32 60 3 0") == true)

-- Hyprland sends layout messages to the focused workspace, not the addressed
-- window's workspace. Exact placement/restore must use the target's context.
do
    local exact_provider = dofile(arg[1])
    local function exact_fixture(address, monitor, workspace_id)
        local area = WORK_AREAS[monitor]
        local value = {
            index = 1,
            window = {
                stable_id = address,
                address = address,
                active = false,
                monitor = { name = monitor },
                workspace = { id = workspace_id, active = true },
            },
            box = { x = area.x, y = area.y, w = 633, h = 593 },
            placements = 0,
        }
        function value:place(box)
            place_target(self, box)
        end
        return { area = area, targets = { value } }, value
    end

    local focused_context, focused_target = exact_fixture("0xa0", "HDMI-A-1", 101)
    focused_target.window.active = true
    local remote_context, remote_target = exact_fixture("0xb0", "DP-8", 103)
    exact_provider.recalculate(focused_context)
    exact_provider.recalculate(remote_context)
    local focused_placements = focused_target.placements
    assert(exact_provider.layout_msg(
        focused_context, "restore 0xb0 usb-c 3 2 1 0 2 1") == true)
    assert(remote_target.placed.x == 2563)
    assert(focused_target.placements == focused_placements)

    for _, message in ipairs({
        "resize 0xb0 right usb-c 3 2",
        "translate 0xb0 right usb-c 3 2",
        "transfer 0xb0 samsung 8 2 bottom 0.5",
        "cancel 0xb0",
    }) do
        assert(exact_provider.layout_msg(focused_context, message)
            == "obsidience: target unavailable")
    end
    local cancelled_context, cancelled_target = exact_fixture("0xc0", "DP-8", 106)
    exact_provider.recalculate(cancelled_context)
    assert(exact_provider.layout_msg(
        focused_context, "place 0xc0 samsung 8 2 7 1 8 2") == true)
    assert(exact_provider.layout_msg(focused_context, "place-cancel 0xc0") == true)
    cancelled_target.window.monitor = { name = "HDMI-A-1" }
    cancelled_target.window.workspace = { id = 107, active = true }
    exact_provider.recalculate({
        area = WORK_AREAS["HDMI-A-1"], targets = { cancelled_target },
    })
    assert(cancelled_target.placed.x < 4000)

    assert(exact_provider.layout_msg(
        focused_context, "place 0xb0 samsung 8 2 7 1 8 2") == true)

    -- The source callback survives when its last window leaves. Until the
    -- destination has a current callback, neither source geometry nor a new
    -- inferred context may authorize another placement.
    remote_target.window.monitor = { name = "HDMI-A-1" }
    remote_target.window.workspace = { id = 104, active = true }
    local before_stale = remote_target.placements
    assert(exact_provider.layout_msg(
        remote_context, "restore 0xb0 samsung 8 2 0 0 1 1")
        == "obsidience: target unavailable")
    assert(remote_target.placements == before_stale)
    local destination_context = {
        area = WORK_AREAS["HDMI-A-1"], targets = { remote_target },
    }
    exact_provider.recalculate(destination_context)
    assert(remote_target.placed.x > 4000 and remote_target.placed.y > 700)
    assert(exact_provider.layout_msg(
        remote_context, "restore 0xb0 samsung 8 2 0 0 1 1") == true)
    assert(remote_target.placed.x == 5 and remote_target.placed.y == 5)
    before_stale = remote_target.placements
    assert(exact_provider.layout_msg(
        remote_context, "restore 0xb0 usb-c 3 2 0 0 1 1")
        == "obsidience: target is on another surface")
    assert(remote_target.placements == before_stale)

    -- Even a matching supplied context cannot win over a conflicting exact
    -- address in another current workspace.
    local duplicate_context = exact_fixture("0xb0", "HDMI-A-2", 105)
    exact_provider.recalculate(duplicate_context)
    assert(exact_provider.layout_msg(
        destination_context, "place 0xb0 samsung 8 2")
        == "obsidience: target unavailable")
    assert(remote_target.placements == before_stale)
end
