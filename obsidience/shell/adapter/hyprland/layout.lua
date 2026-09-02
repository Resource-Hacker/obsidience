-- Project the Obsidience workspace grid onto native Hyprland windows.

local GAP = 5
local DEFAULT_GRIDS = {
    ["HDMI-A-1"] = { surface = "samsung", columns = 8, rows = 2 },
    ["DP-8"] = { surface = "usb-c", columns = 3, rows = 2 },
    ["HDMI-A-2"] = { surface = "dp-4", columns = 4, rows = 1 },
}

local grid_overrides = {}
local contexts = {}
local transfers = {}
local last_placed = {}

local function rounded(value)
    return math.floor(value + 0.5)
end

local function clamped(value, minimum, maximum)
    return math.max(minimum, math.min(maximum, value))
end

local function target_id(target)
    local window = target.window
    return window and tostring(window.stable_id) or "group:" .. tostring(target.index)
end

local function target_grid(target)
    local window = target.window
    local monitor = window and window.monitor
    local defaults = monitor and DEFAULT_GRIDS[monitor.name]
    if not defaults then
        return nil
    end
    local override = grid_overrides[defaults.surface]
    return override or defaults
end

local function context_id(target, grid)
    local window = target.window
    local workspace = window and window.workspace
    return grid.surface .. ":" .. tostring(workspace and workspace.id or 0)
end

local function bounds(grid, left, top, right, bottom)
    return {
        surface = grid.surface,
        columns = grid.columns,
        rows = grid.rows,
        left = left,
        top = top,
        right = right,
        bottom = bottom,
    }
end

local function adapt(value, grid)
    if value.columns == grid.columns and value.rows == grid.rows then
        value.surface = grid.surface
        return value
    end
    local left = clamped(rounded(value.left * grid.columns / value.columns), 0, grid.columns - 1)
    local top = clamped(rounded(value.top * grid.rows / value.rows), 0, grid.rows - 1)
    local right = clamped(rounded(value.right * grid.columns / value.columns), left + 1, grid.columns)
    local bottom = clamped(rounded(value.bottom * grid.rows / value.rows), top + 1, grid.rows)
    return bounds(grid, left, top, right, bottom)
end

local function infer(ctx, target, grid)
    local area = ctx.area
    local box = target.box
    if not box or area.w <= 0 or area.h <= 0 or box.w <= 0 or box.h <= 0 then
        return nil
    end
    local left = clamped(rounded((box.x - area.x) * grid.columns / area.w), 0, grid.columns - 1)
    local top = clamped(rounded((box.y - area.y) * grid.rows / area.h), 0, grid.rows - 1)
    local right = clamped(rounded((box.x + box.w - area.x) * grid.columns / area.w), left + 1, grid.columns)
    local bottom = clamped(rounded((box.y + box.h - area.y) * grid.rows / area.h), top + 1, grid.rows)
    return bounds(grid, left, top, right, bottom)
end

local function same_box(left, right)
    return left and right
        and rounded(left.x) == rounded(right.x)
        and rounded(left.y) == rounded(right.y)
        and rounded(left.w) == rounded(right.w)
        and rounded(left.h) == rounded(right.h)
end

local function first_free(placements, grid)
    for row = 0, grid.rows - 1 do
        for column = 0, grid.columns - 1 do
            local occupied = false
            for _, value in pairs(placements) do
                if column >= value.left and column < value.right
                        and row >= value.top and row < value.bottom then
                    occupied = true
                    break
                end
            end
            if not occupied then
                return bounds(grid, column, row, column + 1, row + 1)
            end
        end
    end
    return bounds(grid, 0, 0, 1, 1)
end

local function unoccupied(candidate, placements, ignored_id)
    for id, value in pairs(placements) do
        if id ~= ignored_id
                and candidate.left < value.right and candidate.right > value.left
                and candidate.top < value.bottom and candidate.bottom > value.top then
            return false
        end
    end
    return true
end

local function span_for(extent, count, wanted)
    local usable = extent - GAP * (count + 1)
    local best, difference = 1, math.huge
    for span = 1, count do
        local size = rounded(span * usable / count) + (span - 1) * GAP
        local candidate = math.abs(size - wanted)
        if candidate < difference then
            best, difference = span, candidate
        end
    end
    return best
end

local function transferred(ctx, transfer, grid)
    local width = span_for(ctx.area.w, grid.columns, transfer.width)
    local height = span_for(ctx.area.h, grid.rows, transfer.height)
    local left = clamped(rounded(transfer.ratio * grid.columns - width / 2), 0, grid.columns - width)
    local top = clamped(rounded(transfer.ratio * grid.rows - height / 2), 0, grid.rows - height)
    if transfer.edge == "left" then
        left = 0
    elseif transfer.edge == "right" then
        left = grid.columns - width
    elseif transfer.edge == "top" then
        top = 0
    else
        top = grid.rows - height
    end
    return bounds(grid, left, top, left + width, top + height)
end

local function rect_for_bounds(area, value)
    local usable_w = area.w - GAP * (value.columns + 1)
    local usable_h = area.h - GAP * (value.rows + 1)
    local x = area.x + GAP + rounded(value.left * usable_w / value.columns) + value.left * GAP
    local y = area.y + GAP + rounded(value.top * usable_h / value.rows) + value.top * GAP
    local right = area.x + GAP + rounded(value.right * usable_w / value.columns) + (value.right - 1) * GAP
    local bottom = area.y + GAP + rounded(value.bottom * usable_h / value.rows) + (value.bottom - 1) * GAP
    return { x = x, y = y, w = right - x, h = bottom - y }
end

local function sync_context(ctx)
    local first = ctx.targets[1]
    local grid = first and target_grid(first)
    if not grid then
        return nil, nil
    end
    local key = context_id(first, grid)
    local state = contexts[key]
    local fresh = state == nil
    if fresh then
        state = { placements = {} }
        contexts[key] = state
    end
    local present = {}
    for _, target in ipairs(ctx.targets) do
        local id = target_id(target)
        present[id] = true
        local transfer = transfers[id]
        local value = state.placements[id]
        if transfer and transfer.surface == grid.surface then
            value = transferred(ctx, transfer, grid)
            transfers[id] = nil
        elseif last_placed[id] and not same_box(target.box, last_placed[id]) then
            local candidate = infer(ctx, target, grid)
            if candidate and unoccupied(candidate, state.placements, id) then
                value = candidate
            elseif value then
                value = adapt(value, grid)
            end
        elseif value then
            value = adapt(value, grid)
        elseif fresh then
            value = infer(ctx, target, grid)
            if value and not unoccupied(value, state.placements) then
                value = nil
            end
        end
        state.placements[id] = value or first_free(state.placements, grid)
    end
    for id in pairs(state.placements) do
        if not present[id] then
            state.placements[id] = nil
        end
    end
    return state, grid
end

local function active_target(ctx)
    for _, target in ipairs(ctx.targets) do
        if target.window and target.window.active == true then
            return target
        end
    end
    return nil
end

local function valid_grid(surface, columns, rows)
    return (surface == "samsung" or surface == "usb-c" or surface == "dp-4")
        and columns and columns >= 1 and columns <= 16 and columns == math.floor(columns)
        and rows and rows >= 1 and rows <= 16 and rows == math.floor(rows)
end

local provider = {
    recalculate = function(ctx)
        local state = sync_context(ctx)
        if not state then
            return
        end
        for _, target in ipairs(ctx.targets) do
            local id = target_id(target)
            local box = rect_for_bounds(ctx.area, state.placements[id])
            target:place(box)
            last_placed[id] = box
        end
    end,

    layout_msg = function(ctx, message)
        local tokens = {}
        for token in message:gmatch("%S+") do
            table.insert(tokens, token)
        end
        if tokens[1] == "grid" then
            local columns, rows = tonumber(tokens[3]), tonumber(tokens[4])
            if #tokens ~= 4 or not valid_grid(tokens[2], columns, rows) then
                return "obsidience: invalid grid"
            end
            grid_overrides[tokens[2]] = {
                surface = tokens[2],
                columns = columns,
                rows = rows,
            }
            return true
        end
        local target = active_target(ctx)
        if not target then
            return "obsidience: no active native window"
        end
        local id = target_id(target)
        if tokens[1] == "cancel" then
            transfers[id] = nil
            return true
        end
        if tokens[1] == "transfer" then
            local columns, rows = tonumber(tokens[3]), tonumber(tokens[4])
            local edge, ratio = tokens[5], tonumber(tokens[6])
            if #tokens ~= 6 or not valid_grid(tokens[2], columns, rows)
                    or not (edge == "left" or edge == "right" or edge == "top" or edge == "bottom")
                    or not ratio or ratio < 0 or ratio > 1 then
                return "obsidience: invalid transfer"
            end
            grid_overrides[tokens[2]] = { surface = tokens[2], columns = columns, rows = rows }
            transfers[id] = {
                surface = tokens[2],
                width = target.box.w,
                height = target.box.h,
                edge = edge,
                ratio = ratio,
            }
            return true
        end

        local columns, rows = tonumber(tokens[4]), tonumber(tokens[5])
        if #tokens ~= 5 or (tokens[1] ~= "resize" and tokens[1] ~= "translate")
                or not (tokens[2] == "left" or tokens[2] == "right"
                    or tokens[2] == "top" or tokens[2] == "bottom")
                or not valid_grid(tokens[3], columns, rows) then
            return "obsidience: invalid layout command"
        end
        grid_overrides[tokens[3]] = { surface = tokens[3], columns = columns, rows = rows }
        local state, grid = sync_context(ctx)
        local value = state and state.placements[id]
        if not value or grid.surface ~= tokens[3] then
            return "obsidience: active window is on another surface"
        end
        value = adapt(value, grid_overrides[tokens[3]])
        local direction = tokens[2]
        if tokens[1] == "translate" then
            local dx = direction == "left" and -1 or direction == "right" and 1 or 0
            local dy = direction == "top" and -1 or direction == "bottom" and 1 or 0
            if value.left + dx >= 0 and value.right + dx <= value.columns
                    and value.top + dy >= 0 and value.bottom + dy <= value.rows then
                value.left, value.right = value.left + dx, value.right + dx
                value.top, value.bottom = value.top + dy, value.bottom + dy
            end
        elseif direction == "left" then
            if value.left > 0 then value.left = value.left - 1
            elseif value.right - value.left > 1 then value.right = value.right - 1 end
        elseif direction == "right" then
            if value.right < value.columns then value.right = value.right + 1
            elseif value.right - value.left > 1 then value.left = value.left + 1 end
        elseif direction == "top" then
            if value.top > 0 then value.top = value.top - 1
            elseif value.bottom - value.top > 1 then value.bottom = value.bottom - 1 end
        elseif direction == "bottom" then
            if value.bottom < value.rows then value.bottom = value.bottom + 1
            elseif value.bottom - value.top > 1 then value.top = value.top + 1 end
        end
        state.placements[id] = value
        return true
    end,
}

hl.layout.register("obsidience", provider)

return provider
