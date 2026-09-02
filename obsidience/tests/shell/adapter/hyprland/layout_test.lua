local registered_name = nil
local provider = nil

hl = {
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
    stable_id = 7,
    active = true,
    monitor = { name = "HDMI-A-1" },
    workspace = { id = 1 },
}
local target = {
    index = 1,
    window = window,
    box = { x = 5, y = 5, w = 634, h = 713 },
}
function target:place(box)
    self.placed = box
    self.box = box
end

local context = {
    area = { x = 0, y = 0, w = 5120, h = 1440 },
    targets = { target },
}

provider.recalculate(context)
assert(target.placed.x == 5 and target.placed.y == 5)
assert(target.placed.w == 634 and target.placed.h == 713)

assert(provider.layout_msg(context, "resize right samsung 8 2") == true)
provider.recalculate(context)
assert(target.placed.x == 5 and target.placed.w == 1274)

assert(provider.layout_msg(context, "translate right samsung 8 2") == true)
provider.recalculate(context)
assert(target.placed.x == 644 and target.placed.w == 1274)

assert(provider.layout_msg(context, "transfer usb-c 3 2 top 0.5") == true)
window.monitor = { name = "DP-8" }
window.workspace = { id = 3 }
context.area = { x = 1920, y = 1440, w = 1920, h = 1200 }
provider.recalculate(context)
assert(target.placed.x == 2563 and target.placed.y == 1445)
assert(target.placed.w == 1272 and target.placed.h == 593)

window.active = false
assert(provider.layout_msg(context, "resize left usb-c 3 2")
    == "obsidience: no active native window")

local second_window = {
    stable_id = 8,
    active = false,
    monitor = { name = "HDMI-A-2" },
    workspace = { id = 10 },
}
local third_window = {
    stable_id = 9,
    active = false,
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
    self.placed = box
    self.box = box
end
function third_target:place(box)
    self.placed = box
    self.box = box
end

provider.recalculate({
    area = { x = 0, y = 1440, w = 1920, h = 550 },
    targets = { second_target, third_target },
})
assert(second_target.placed.x == 5)
assert(third_target.placed.x == 484)

local drop_window = {
    stable_id = 10,
    active = true,
    monitor = { name = "HDMI-A-1" },
    workspace = { id = 11 },
}
local drop_target = {
    index = 1,
    window = drop_window,
    box = { x = 5, y = 5, w = 634, h = 713 },
}
function drop_target:place(box)
    self.placed = box
    self.box = box
end
local drop_context = {
    area = { x = 0, y = 0, w = 5120, h = 1440 },
    targets = { drop_target },
}
provider.recalculate(drop_context)
drop_target.box = { x = 1284, y = 723, w = 634, h = 712 }
provider.recalculate(drop_context)
assert(drop_target.placed.x == 1284 and drop_target.placed.y == 723)
assert(drop_target.placed.w == 634 and drop_target.placed.h == 712)
